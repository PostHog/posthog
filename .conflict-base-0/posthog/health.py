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

from collections.abc import Callable
from typing import Literal, cast, get_args
from urllib.parse import urljoin

from django.conf import settings
from django.core.cache import cache
from django.db import DEFAULT_DB_ALIAS, connections
from django.db.migrations.executor import MigrationExecutor
from django.http import HttpRequest, HttpResponse, JsonResponse

import requests
from structlog import get_logger

from posthog.celery import app
from posthog.database_healthcheck import DATABASE_FOR_FLAG_MATCHING
from posthog.kafka_client.client import can_connect as can_connect_to_kafka

logger = get_logger(__name__)

ServiceRole = Literal["events", "web", "worker", "decide", "query", "report"]

service_dependencies: dict[ServiceRole, list[str]] = {
    "events": ["http", "kafka_connected"],
    "web": [
        "http",
        # NOTE: we include Postgres because the way we use django means every request hits the DB
        # https://posthog.slack.com/archives/C02E3BKC78F/p1679669676438729
        "postgres",
        # NOTE: migrations run in a separate job before the version is even deployed. This check is unnecessary
        # "postgres_migrations_uptodate",
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
        # NOTE: migrations run in a separate job before the version is even deployed. This check is unnecessary
        # "postgres_migrations_uptodate",
        "clickhouse",
        "celery_broker",
    ],
    "decide": ["http"],
    "query": ["http", "postgres", "cache"],
    "report": ["http", "kafka_connected"],
}

# if atleast one of the checks is True, then the service is considered healthy
# for the given role
service_conditional_dependencies: dict[ServiceRole, list[str]] = {
    "decide": ["cache", "postgres_flags"],
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

    available_checks: dict[str, Callable] = {
        "clickhouse": is_clickhouse_connected,
        "postgres": is_postgres_connected,
        "postgres_flags": lambda: is_postgres_connected(DATABASE_FOR_FLAG_MATCHING),
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

    return JsonResponse({**evaluated_checks, **evaluated_conditional_checks}, status=status)


def is_kafka_connected() -> bool:
    """
    Check that we can reach Kafka,

    Returns `True` if connected, `False` otherwise.

    NOTE: we are only checking the Producer here, as currently this process
    does not Consume from Kafka.
    """
    return can_connect_to_kafka()


def is_postgres_connected(db_alias=DEFAULT_DB_ALIAS) -> bool:
    """
    Check we can reach the main postgres and perform a super simple query

    Returns `True` if so, `False` otherwise
    """
    try:
        with connections[db_alias].cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        logger.exception("postgres_connection_failure", exc_info=True)
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
    except Exception:
        logger.debug("postgres_migrations_check_failure", exc_info=True)
        return False

    return not plan


def is_clickhouse_connected() -> bool:
    """
    Check we can ping the ClickHouse cluster.

    Returns `True` if so, `False` otherwise
    """
    ping_url = urljoin(settings.CLICKHOUSE_HTTP_URL, "ping")
    try:
        response = requests.get(ping_url, timeout=3, verify=False)
        response.raise_for_status()
    except Exception:
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
    except Exception:
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
    except Exception:
        # NOTE: We catch all exceptions here because we never want to throw from these checks
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
