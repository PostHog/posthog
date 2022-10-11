from typing import Optional

from django.conf import settings
from django.db.utils import ProgrammingError

is_cloud_cached: Optional[bool] = None

# NOTE: This is cached for the lifetime of the instance but this is not an issue as the value is not expected to change
def is_cloud():
    global is_cloud_cached

    if not settings.TEST and isinstance(is_cloud_cached, bool):
        return is_cloud_cached

    try:
        from ee.models import License

        # TRICKY - The license table may not exist if a migration is running
        license = License.objects.first_valid()
        is_cloud_cached = license.plan == "cloud" if license else settings.MULTI_TENANCY
        return is_cloud_cached
    # TRICKY - The license table may not exist if a migration is running
    except (ImportError, ProgrammingError):
        return False
