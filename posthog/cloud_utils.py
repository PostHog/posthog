from typing import TYPE_CHECKING, Any, Optional

from django.conf import settings
from django.db.utils import ProgrammingError
from sentry_sdk import capture_exception

if TYPE_CHECKING:
    from ee.models.license import License

is_cloud_cached: Optional[bool] = None
is_instance_licensed_cached: Optional[bool] = None
instance_license_cached: Optional["License"] = None


# NOTE: This is cached for the lifetime of the instance but this is not an issue as the value is not expected to change
def is_cloud():
    return True
    global is_cloud_cached

    if not settings.EE_AVAILABLE:
        return False

    if isinstance(is_cloud_cached, bool):
        return is_cloud_cached

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
def TEST_clear_cloud_cache(value: Optional[bool] = None):
    global is_cloud_cached
    is_cloud_cached = value


def get_cached_instance_license() -> Optional["License"]:
    """Returns the first valid license and caches the value for the lifetime of the instance, as it is not expected to change.
    If there is no valid license, it returns None.
    """
    global instance_license_cached
    global is_instance_licensed_cached

    try:
        from ee.models.license import License
    except ProgrammingError:
        # TRICKY - The license table may not exist if a migration is running
        pass
    except Exception as e:
        capture_exception(e)
        return None

    if isinstance(instance_license_cached, License):
        return instance_license_cached

    if is_instance_licensed_cached is False:
        # This is an unlicensed instance
        return None

    # TRICKY - The license table may not exist if a migration is running
    license = License.objects.first_valid()
    if license:
        instance_license_cached = license
        is_instance_licensed_cached = True
    else:
        is_instance_licensed_cached = False
    return instance_license_cached


# NOTE: This is purely for testing purposes
def TEST_clear_instance_license_cache(
    is_instance_licensed: Optional[bool] = None, instance_license: Optional[Any] = None
):
    global instance_license_cached
    instance_license_cached = instance_license
    global is_instance_licensed_cached
    is_instance_licensed_cached = is_instance_licensed
