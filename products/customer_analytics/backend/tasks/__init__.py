# Re-exported so Celery autodiscovers the task when the tasks package is imported.
from products.customer_analytics.backend.tasks.tasks import process_custom_property_sync  # noqa: F401
