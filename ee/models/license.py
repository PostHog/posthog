from typing import Optional

from django.contrib.auth import get_user_model
from django.db import models
from django.db.models import Q
from django.utils import timezone
from rest_framework import exceptions, status

from posthog.models.utils import sane_repr


class LicenseError(exceptions.APIException):
    """
    Exception raised for licensing errors.
    """

    default_type = "license_error"
    default_code = "license_error"
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "There was a problem with your current license."

    def __init__(self, code, detail):
        self.code = code
        self.detail = exceptions._get_error_details(detail, code)


class LicenseManager(models.Manager):
    def first_valid(self) -> Optional["License"]:
        """Return the highest valid license or cloud licenses if any"""
        valid_licenses = list(self.filter(Q(valid_until__gte=timezone.now()) | Q(plan="cloud")))
        if not valid_licenses:
            return None
        return max(
            valid_licenses,
            key=lambda license: License.PLAN_TO_SORTING_VALUE.get(license.plan, 0),
        )


class License(models.Model):
    objects: LicenseManager = LicenseManager()

    created_at = models.DateTimeField(auto_now_add=True)
    plan = models.CharField(max_length=200)
    valid_until = models.DateTimeField()
    key = models.CharField(max_length=200)
    # DEPRECATED: This is no longer used
    max_users = models.IntegerField(default=None, null=True)  # None = no restriction

    @property
    def is_v2_license(self) -> bool:
        return self.key and len(self.key.split("::")) == 2

    __repr__ = sane_repr("key", "plan", "valid_until")


def get_licensed_users_available() -> Optional[int]:
    """
    Returns the number of user slots available that can be created based on the instance's current license.
    Not relevant for cloud users.
    `None` means unlimited users.
    """

    license = License.objects.first_valid()
    from posthog.models import OrganizationInvite

    if license:
        if license.max_users is None:
            return None

        users_left = license.max_users - get_user_model().objects.count() - OrganizationInvite.objects.count()
        return max(users_left, 0)

    return None
