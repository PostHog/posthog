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

from django.db import DEFAULT_DB_ALIAS
from django.db import Error as DjangoDatabaseError
from django.db import connections
from django.db.migrations.executor import MigrationExecutor
from django.http import JsonResponse

from ee.kafka_client.client import can_connect as can_connect_to_kafka


def livez(request):
    """
    Endpoint to be used to identify if the service is still functioning, in a
    minimal state. Note that we do not check dependencies here, but are just
    interested that the service hasn't completely locked up. It's a weaker check
    than readyz but we can hit this harder such that we can take obviously
    broken pods out asap.
    """
    return JsonResponse({"http": True})


def readyz(request):
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
    """
    exclude = set(request.GET.getlist("exclude", []))

    checks = {
        "http": True,
        "postgres": is_postgres_connected(),
        "postgres_migrations_uptodate": are_postgres_migrations_uptodate(),
        "kafka_connected": is_kafka_connected(),
    }

    status = 200 if all(check_status for name, check_status in checks.items() if name not in exclude) else 503

    return JsonResponse(checks, status=status)


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
        return False
    return False if plan else True
