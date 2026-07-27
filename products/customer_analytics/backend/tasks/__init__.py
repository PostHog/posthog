# Re-exported so Celery autodiscovers the tasks when the tasks package is imported.
from products.customer_analytics.backend.tasks.tasks import (  # noqa: F401
    process_custom_property_sync,
    send_announcement,
)
