import os
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Optional

from django.conf import settings
from django.db.utils import ProgrammingError
from django.utils import timezone

from posthog.exceptions_capture import capture_exception

if TYPE_CHECKING:
    from ee.models.license import License

is_cloud_cached: Optional[bool] = None
is_instance_licensed_cached: Optional[bool] = None
instance_license_cached: Optional["License"] = None


def is_cloud() -> bool:
    return bool(settings.CLOUD_DEPLOYMENT)


def is_dev_mode() -> bool:
    return bool(settings.DEBUG)


def is_ci() -> bool:
    return os.environ.get("GITHUB_ACTIONS") is not None


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

    # No license found locally, create one for dev mode
    if not license and is_dev_mode():
        dev_uuid = "69004a5f-a7da-499a-a63a-338f996b6f7a"
        license = License.objects.create(
            key=f"{dev_uuid}::{settings.LICENSE_SECRET_KEY}",
            plan="enterprise",
            valid_until=timezone.now() + timedelta(weeks=52),
        )

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


def get_api_host():
    if settings.SITE_URL == "https://us.posthog.com":
        return "https://us.i.posthog.com"
    elif settings.SITE_URL == "https://eu.posthog.com":
        return "https://eu.i.posthog.com"
    return settings.SITE_URL
