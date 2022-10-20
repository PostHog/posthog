from typing import Optional

from django.conf import settings
from django.db.utils import ProgrammingError
from sentry_sdk import capture_exception

is_cloud_cached: Optional[bool] = None

# NOTE: This is cached for the lifetime of the instance but this is not an issue as the value is not expected to change
def is_cloud():
    global is_cloud_cached

    if not settings.EE_AVAILABLE:
        return False

    if isinstance(is_cloud_cached, bool):
        return is_cloud_cached

    # Until billing-v2 is fully migrated, multi-tenancy take priority
    is_cloud_cached = str(settings.MULTI_TENANCY).lower() in ("true", "1")

    if not is_cloud_cached:
        try:
            # NOTE: Important not to import this from ee.models as that will cause a circular import for celery
            from ee.models.license import License

            # TRICKY - The license table may not exist if a migration is running
            license = License.objects.first_valid()
            is_cloud_cached = license.plan == "cloud" if license else False
        except ProgrammingError:
            # TRICKY - The license table may not exist if a migration is running
            pass
        except Exception as e:
            print("ERROR: Unable to check license", e)  # noqa: T201
            capture_exception(e)

    return is_cloud_cached


# NOTE: This is purely for testing purposes
def TEST_clear_cloud_cache():
    global is_cloud_cached
    is_cloud_cached = None
