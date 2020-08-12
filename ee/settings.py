CLICKHOUSE_DATABASES = {
    "default": {"db_name": "default", "username": "default", "password": "", "migrate": True, "readonly": False},
}
CLICKHOUSE_REDIS_CONFIG = {"host": "localhost", "port": 6379, "db": 8}
CLICKHOUSE_CELERY_QUEUE = "clickhouse"
CLICKHOUSE_MODELS_MODULE = "ee.clickhouse.models"
CLICKHOUSE_MIGRATIONS_PACKAGE = "clickhouse.migrations"
from datetime import timedelta

CELERYBEAT_SCHEDULE = {
    "clickhouse_auto_sync": {
        "task": "django_clickhouse.tasks.clickhouse_auto_sync",
        "schedule": timedelta(seconds=2),  # Every 2 seconds
        "options": {"expires": 1, "queue": CLICKHOUSE_CELERY_QUEUE},
    }
}
