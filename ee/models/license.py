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
    def create(self, *args: Any, **kwargs: Any):
        validate = requests.post("https://license.posthog.com/validate_license", data={"key": kwargs["key"]})
        resp = validate.json()
        if not validate.ok:
            raise LicenseError(resp["code"], resp["detail"])

        kwargs["valid_until"] = resp["data"]["valid_until"]
        kwargs["plan"] = resp["data"]["plan"]
        return super().create(*args, **kwargs)


class License(models.Model):
    objects = LicenseManager()

    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    plan: models.CharField = models.CharField(max_length=200)
    valid_until: models.DateTimeField = models.DateTimeField()
    key: models.CharField = models.CharField(max_length=200)

    ENTERPRISE_PLAN = "enterprise"
    ENTERPRISE_FEATURES = ["zapier"]
    PLANS = {ENTERPRISE_PLAN: ENTERPRISE_FEATURES}
