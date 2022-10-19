from typing import Optional

from django.conf import settings
from django.db.utils import ProgrammingError

is_cloud_cached: Optional[bool] = None

# NOTE: This is cached for the lifetime of the instance but this is not an issue as the value is not expected to change
def is_cloud():
    global is_cloud_cached

    if isinstance(is_cloud_cached, bool):
        return is_cloud_cached

    # Until billing-v2 is fully migrated, multi-tenancy take priority
    is_cloud_cached = settings.MULTI_TENANCY

    if not is_cloud_cached:
        try:
            from ee.models import License

            # TRICKY - The license table may not exist if a migration is running
            license = License.objects.first_valid()
            is_cloud_cached = license.plan == "cloud" if license else False
        # TRICKY - The license table may not exist if a migration is running
        except (ImportError, ProgrammingError) as e:
            is_cloud_cached = False

    return is_cloud_cached


# NOTE: This is purely for testing purposes
def TEST_clear_cloud_cache():
    global is_cloud_cached
    is_cloud_cached = None
