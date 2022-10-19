from codecs import escape_encode
from typing import Optional

from django.conf import settings
from django.db.utils import ProgrammingError

is_cloud_cached: Optional[bool] = None

# NOTE: This is cached for the lifetime of the instance but this is not an issue as the value is not expected to change
def is_cloud():
    global is_cloud_cached

    if isinstance(is_cloud_cached, bool):
        return is_cloud_cached

    try:
        from ee.models import License

        # TRICKY - The license table may not exist if a migration is running
        license = License.objects.first_valid()
        is_cloud_cached = settings.MULTI_TENANCY or (license.plan == "cloud" if license else False)
        return is_cloud_cached
    # TRICKY - The license table may not exist if a migration is running
    except (ImportError, ProgrammingError) as e:
        return False


# NOTE: This is purely for testing purposes
def TEST_clear_cloud_cache():
    global is_cloud_cached
    is_cloud_cached = None
