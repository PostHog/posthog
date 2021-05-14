from typing import Any, ClassVar, List, Optional, cast

import requests
from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone
from rest_framework import exceptions, status


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
    def create(self, *args: Any, **kwargs: Any) -> "License":
        validate = requests.post("https://license.posthog.com/licenses/activate", data={"key": kwargs["key"]})
        resp = validate.json()
        if not validate.ok:
            raise LicenseError(resp["code"], resp["detail"])

        kwargs["valid_until"] = resp["valid_until"]
        kwargs["plan"] = resp["plan"]
        kwargs["max_users"] = resp.get("max_users", 0)
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
    FREE_CLICKHOUSE_PLAN = "free_clickhouse"
    ENTERPRISE_FEATURES = [
        "zapier",
        "organizations_projects",
        "google_login",
        "dashboard_collaboration",
    ]  # Base premium features
    PLANS = {
        ENTERPRISE_PLAN: ENTERPRISE_FEATURES + ["clickhouse"],
        FREE_CLICKHOUSE_PLAN: ["clickhouse"],
    }

    @property
    def available_features(self) -> List[str]:
        return self.PLANS.get(self.plan, [])


def get_max_users() -> Optional[int]:
    """
    Returns the maximum number of users allowed.
    Examines all available valid licenses and returns the max users available.
    """
    licenses = License.objects.filter(valid_until__gte=timezone.now())
    if len(licenses) > 0:
        return max([l.max_users for l in licenses])
    else:
        return None


def get_licensed_users_available() -> Optional[int]:
    """
    Returns the number of user slots available that can be created based on the instance's current license.
    Not relevant for cloud users.
    `None` means unlimited users.
    """

    max_users = get_max_users()
    from posthog.models import OrganizationInvite

    if license:
        if max_users is None:
            return None

        users_left = max_users - get_user_model().objects.count() - OrganizationInvite.objects.count()
        return max(users_left, 0)

    return None
