from django.db import DEFAULT_DB_ALIAS
from django.db import Error as DjangoDatabaseError
from django.db import connections
from django.db.migrations.executor import MigrationExecutor
from django.http import JsonResponse

from ee.kafka_client.client import KafkaProducer


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
        "db": health_db(),
        "db_migrations_uptodate": health_migrations(),
        "kafka_connected": health_kafka(),
    }

    status = 200 if all(check_status for name, check_status in checks.items() if name not in exclude) else 503

    return JsonResponse(checks, status=status)


def health_kafka() -> bool:
    """
    Check that we can reach Kafka,

    Returns `True` if connected, `False` otherwise.

    NOTE: we are only checking the Producer here, as currently this process
    does not Consume from Kafka.
    """
    return KafkaProducer().bootstrap_connected()


def health_db() -> bool:
    """
    Check we can reach the main db and perform a super simple query

    Returns `True` if so, `False` otherwise
    """
    try:
        with connections[DEFAULT_DB_ALIAS].cursor() as cursor:
            cursor.execute("SELECT 1")
    except DjangoDatabaseError:
        return False

    return True


def health_migrations() -> bool:
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
