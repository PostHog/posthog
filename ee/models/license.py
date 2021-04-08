from typing import Any, List, Optional, cast

import requests
from django.db import models
from django.utils import timezone


class LicenseError(Exception):
    """Exception raised for licensing errors.

    Attributes:
        code -- code of the exception
        detail -- message of the exception
    """

    def __init__(self, code, detail):
        self.code = code
        self.detail = detail


class LicenseManager(models.Manager):
    def create(self, *args: Any, **kwargs: Any) -> "License":
        validate = requests.post("http://127.0.0.1:3000/licenses/activate", data={"key": kwargs["key"]})
        resp = validate.json()
        if not validate.ok:
            print(resp)
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
    max_users: models.IntegerField = models.IntegerField(default=0)

    ENTERPRISE_PLAN = "enterprise"
    ENTERPRISE_FEATURES = ["clickhouse", "zapier", "organizations_projects", "google_login", "dashboard_collaboration"]
    PLANS = {
        ENTERPRISE_PLAN: ENTERPRISE_FEATURES,
    }

    FREE_CLICKHOUSE_PLAN = "free_clickhouse"
    FREE_CLICKHOUSE_FEATURES = ["clickhouse"]
    PLANS = {FREE_CLICKHOUSE_PLAN: FREE_CLICKHOUSE_FEATURES}

    @property
    def available_features(self) -> List[str]:
        return self.PLANS.get(self.plan, [])
