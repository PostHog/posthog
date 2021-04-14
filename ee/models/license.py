from typing import Any, ClassVar, List, Optional, cast

import requests
from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone
from rest_framework import exceptions, status

from posthog.models import OrganizationInvite


class LicenseError(exceptions.APIException):
    """
    Exception raised for licensing errors.
    """

    default_type: ClassVar[str] = "license_error"
    default_code: ClassVar[str] = "license_error"
    status_code: ClassVar[int] = status.HTTP_400_BAD_REQUEST
    default_detail: ClassVar[str] = "There was a problem with your current license."

    def __init__(self, code, detail):
        self.code = code
        self.detail = exceptions._get_error_details(detail, code)


class LicenseManager(models.Manager):
    def create(self, *args: Any, **kwargs: Any) -> "License":
        validate = requests.post("https://license.posthog.com/licenses/activate", data={"key": kwargs["key"]})
        resp = validate.json()
        if not validate.ok:
            raise LicenseError(resp["code"], resp["detail"])

        kwargs["valid_until"] = resp["valid_until"]
        kwargs["plan"] = resp["plan"]
        kwargs["max_users"] = resp["max_users"]
        return cast(License, super().create(*args, **kwargs))

    def first_valid(self) -> Optional["License"]:
        return cast(Optional[License], (self.filter(valid_until__gte=timezone.now()).first()))


class License(models.Model):
    objects = LicenseManager()

    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    plan: models.CharField = models.CharField(max_length=200)
    valid_until: models.DateTimeField = models.DateTimeField()
    key: models.CharField = models.CharField(max_length=200)
    max_users: models.IntegerField = models.IntegerField(default=None, null=True)  # None = no restriction

    ENTERPRISE_PLAN = "enterprise"
    BASE_CLICKHOUSE_PLAN = "base_clickhouse"
    PLANS = {
        ENTERPRISE_PLAN: ["clickhouse", "zapier", "organizations_projects", "google_login", "dashboard_collaboration"],
        BASE_CLICKHOUSE_PLAN: ["clickhouse"],
    }

    @property
    def available_features(self) -> List[str]:
        return self.PLANS.get(self.plan, [])


def get_licensed_users_available() -> Optional[int]:
    """
    Returns the number of user slots available that can be created based on the instance's current license.
    Not relevant for cloud users.
    `None` means unlimited users.
    """

    license = License.objects.first_valid()
    if license:
        if license.max_users is None:
            return None

        users_left = license.max_users - get_user_model().objects.count() - OrganizationInvite.objects.count()
        return max(users_left, 0)

    return None
