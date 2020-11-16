from typing import Any

import requests
from django.db import models


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
        validate = requests.post("https://license.posthog.com/licenses/activate", data={"key": kwargs["key"]})
        resp = validate.json()
        if not validate.ok:
            raise LicenseError(resp["code"], resp["detail"])

        kwargs["valid_until"] = resp["valid_until"]
        kwargs["plan"] = resp["plan"]
        return self._create(*args, **kwargs)

    def _create(self, *args: Any, **kwargs: Any) -> "License":
        return super().create(*args, **kwargs)


class License(models.Model):
    objects = LicenseManager()

    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    plan: models.CharField = models.CharField(max_length=200)
    valid_until: models.DateTimeField = models.DateTimeField()
    key: models.CharField = models.CharField(max_length=200)

    # TODO: This logic should go on posthog-production (requires abstraction on models/organization.py)
    STARTER_PLAN = "starter"  # cloud
    GROWTH_PLAN = "growth"  # cloud
    STARTUP_PLAN = "startup"  # cloud
    STARTER_FEATURES = ["organizations_projects"]

    ENTERPRISE_PLAN = "enterprise"
    ENTERPRISE_FEATURES = ["zapier", "organizations_projects"]
    PLANS = {
        ENTERPRISE_PLAN: ENTERPRISE_FEATURES,
        STARTER_PLAN: STARTER_FEATURES,
        GROWTH_PLAN: ENTERPRISE_FEATURES,
        STARTUP_PLAN: ENTERPRISE_FEATURES,
    }
