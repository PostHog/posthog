from django.db import connections, router

from products.customer_analytics.backend.models import CustomPropertyValue


def get_account_property_sync_generation() -> int:
    using = router.db_for_write(CustomPropertyValue)
    with connections[using].cursor() as cursor:
        # Sequence allocation avoids holding a per-view row lock through an inline caller's transaction.
        cursor.execute("SELECT nextval(pg_get_serial_sequence('customer_analytics_accountpropertysyncstate', 'id'))")
        row = cursor.fetchone()
    assert row is not None
    return int(row[0])
