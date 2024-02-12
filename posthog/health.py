# Defines the healthcheck endpoints to be used by process orchestration system
# deployments to ensure:

#  1. new deployments are not marked as ready if they are misconfigured, e.g.
#     kafka settings are wrong
#  2. pods that are dead for some reason are taken out of service
#  3. traffic is not routed to pods that we know we fail to handle it
#     successfully. e.g. if an events pod can't reach kafka, we know that it
#     shouldn't get http traffic routed to it.

# See
# https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/
# for generic k8s docs on healthchecks.

# I have specifically not reused the statuses in instance_status. These health
# endpoints are for a very specific purpose and we want to make sure that any
# changes to them are deliberate, as otherwise we could introduce unexpected
# behaviour in deployments.

from typing import Callable, Dict, List, Literal, cast, get_args

import amqp.exceptions
import django_redis.exceptions
import kombu.exceptions
import redis.exceptions
from clickhouse_driver.errors import Error as ClickhouseError
from django.core.cache import cache
from django.db import DEFAULT_DB_ALIAS
from django.db import Error as DjangoDatabaseError
from django.db import connections
from django.db.migrations.executor import MigrationExecutor
from django.http import HttpRequest, HttpResponse, JsonResponse
from structlog import get_logger

from posthog.celery import app
from posthog.client import sync_execute
from posthog.kafka_client.client import can_connect as can_connect_to_kafka

logger = get_logger(__name__)

ServiceRole = Literal["events", "web", "worker", "decide"]

service_dependencies: Dict[ServiceRole, List[str]] = {
    "events": ["http", "kafka_connected"],
    "web": [
        "http",
        # NOTE: we include Postgres because the way we use django means every request hits the DB
        # https://posthog.slack.com/archives/C02E3BKC78F/p1679669676438729
        "postgres",
        "postgres_migrations_uptodate",
        "cache",
        # NOTE: we do not include clickhouse for web, as even without clickhouse we
        # want to be able to display something to the user.
        # "clickhouse"
        # NOTE: we do not include "celery_broker" as web could still do lot's of
        # useful things
        # "celery_broker"
    ],
    # NOTE: we can be pretty picky about what the worker needs as by its nature
    # of reading from a durable queue rather that being required to perform
    # request/response, we are more resilient to service downtime.
    "worker": [
        "http",
        "postgres",
        "postgres_migrations_uptodate",
        "clickhouse",
        "celery_broker",
    ],
    "decide": ["http"],
}

# if atleast one of the checks is True, then the service is considered healthy
# for the given role
service_conditional_dependencies: Dict[ServiceRole, List[str]] = {
    "decide": ["cache", "postgres"],
}


def livez(request: HttpRequest):
    """
    Endpoint to be used to identify if the service is still functioning, in a
    minimal state. Note that we do not check dependencies here, but are just
    interested that the service hasn't completely locked up. It's a weaker check
    than readyz but we can hit this harder such that we can take obviously
    broken pods out asap.
    """
    return JsonResponse({"http": True})


def readyz(request: HttpRequest):
    """
    Validate that everything this process need to operate correctly is in place.
    Returns a dict of checks to boolean status, returning 503 status if any of
    them is non-True

    This should be used to validate if the service is ready to serve traffic.
    This can either be HTTP requests, or e.g. if a celery worker should be
    considered ready such that old workers are removed, within a k8s deployment.

    We accept a `exclude` parameter such that we can exclude certain checks from
    producing a 5xx response. This way we can distinguish between the different
    critical dependencies for each k8s deployment, e.g. the events pod 100%
    needs kafka to operate. For the web server however, this is debatable. The
    web server does a lot of stuff, and kafka is only used I believe for sending
    merge person events, so we'd rather stay up with degraded functionality,
    rather than take the website UI down.

    We also accept an optional `role` parameter which can be any `ServiceRole`,
    and can be used to specify that a subset of dependencies should be checked,
    specific to the role a process is playing.
    """
    exclude = set(request.GET.getlist("exclude", []))
    role = request.GET.get("role", None)

    if role and role not in get_args(ServiceRole):
        return JsonResponse({"error": "InvalidRole"}, status=400)

    available_checks = {
        "clickhouse": is_clickhouse_connected,
        "postgres": is_postgres_connected,
        "postgres_migrations_uptodate": are_postgres_migrations_uptodate,
        "kafka_connected": is_kafka_connected,
        "celery_broker": is_celery_broker_connected,
        "cache": is_cache_backend_connected,
    }

    conditional_checks = {}

    if role:
        # If we have a role, then limit the checks to a subset defined by the
        # service_dependencies for this specific role, defaulting to all if we
        # don't find a lookup
        dependencies = service_dependencies.get(cast(ServiceRole, role), available_checks.keys())
        conditional_dependencies = service_conditional_dependencies.get(cast(ServiceRole, role)) or []

        conditional_checks = {
            name: check for name, check in available_checks.items() if name in conditional_dependencies
        }

        available_checks = {name: check for name, check in available_checks.items() if name in dependencies}

    # Run each check and collect the status
    # TODO: handle time bounding checks
    # TODO: handle concurrent checks(?). Only if it becomes an issue, at which
    # point maybe we're doing too many checks or they are too intensive.
    evaluated_checks = {name: check() for name, check in available_checks.items()}
    evaluated_conditional_checks = {name: check() for name, check in conditional_checks.items()}

    prelim_status = (
        200 if all(check_status for name, check_status in evaluated_checks.items() if name not in exclude) else 503
    )

    if prelim_status == 200 and evaluated_conditional_checks:
        # If there are any conditional checks, then run them
        status = 200 if any(check_status for _, check_status in evaluated_conditional_checks.items()) else 503
    else:
        status = prelim_status

    return JsonResponse(evaluated_checks, status=status)


def is_kafka_connected() -> bool:
    """
    Check that we can reach Kafka,

    Returns `True` if connected, `False` otherwise.

    NOTE: we are only checking the Producer here, as currently this process
    does not Consume from Kafka.
    """
    return can_connect_to_kafka()


def is_postgres_connected() -> bool:
    """
    Check we can reach the main postgres and perform a super simple query

    Returns `True` if so, `False` otherwise
    """
    try:
        with connections[DEFAULT_DB_ALIAS].cursor() as cursor:
            cursor.execute("SELECT 1")
    except DjangoDatabaseError:
        logger.debug("postgres_connection_failure", exc_info=True)
        return False

    return True


def are_postgres_migrations_uptodate() -> bool:
    """
    Check that all migrations that the running version of the code knows about
    have been applied.

    Returns `True` if so, `False` otherwise
    """
    try:
        executor = MigrationExecutor(connections[DEFAULT_DB_ALIAS])
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    except DjangoDatabaseError:
        logger.debug("postgres_migrations_check_failure", exc_info=True)
        return False

    return not plan


def is_clickhouse_connected() -> bool:
    """
    Check we can perform a super simple Clickhouse query.

    Returns `True` if so, `False` otherwise
    """
    try:
        sync_execute("SELECT 1")
    except ClickhouseError:
        logger.debug("clickhouse_connection_failure", exc_info=True)
        return False

    return True


def is_celery_broker_connected() -> bool:
    """
    Check we can connect to the celery broker.

    Returns `True` if so, `False` otherwise
    """
    try:
        # NOTE: Possibly not the best way to test that celery broker, it is
        # possibly testing more than just is the broker reachable.
        app.connection_for_read().ensure_connection(timeout=0, max_retries=0)
    except (amqp.exceptions.AMQPError, kombu.exceptions.KombuError):
        # NOTE: I wasn't sure exactly what could be raised, so we get all AMPQ
        # and Kombu errors
        logger.debug("celery_broker_connection_failure", exc_info=True)
        return False

    return True


def is_cache_backend_connected() -> bool:
    """
    Checks if we can connect to redis, used for at least:

     1. django cache
     2. axes failure rate limiting

    Returns `True` if so, `False` otherwise
    """
    try:
        # NOTE: we call has_key just as a method to force the cache to actually
        # connect, otherwise it appears to be lazy, but perhaps there is a more
        # convenient less fragile way to do this. It would be nice if we could
        # have a `check_health` exposed in some generic way, as the python redis
        # client does appear to have something for this task.
        cache.has_key("_connection_test_key")  # noqa: W601
    except (redis.exceptions.RedisError, django_redis.exceptions.ConnectionInterrupted):
        # NOTE: There doesn't seems to be a django cache specific exception
        # here, so we will just have to add which ever exceptions the cache
        # backend uses. For our case we're using django_redis, which does define
        # some exceptions but appears to mostly just pass through the underlying
        # redis exception.
        logger.debug("cache_backend_connection_failure", exc_info=True)
        return False

    return True


def healthcheck_middleware(get_response: Callable[[HttpRequest], HttpResponse]):
    """
    Middleware to serve up ready and liveness responses without executing any
    inner middleware. Otherwise, if paths do not match these healthcheck
    endpoints, we pass the request down the chain.
    """

    def middleware(request: HttpRequest) -> HttpResponse:
        if request.path == "/_readyz":
            return readyz(request)

        elif request.path == "/_livez":
            return livez(request)

        return get_response(request)

    return middleware
