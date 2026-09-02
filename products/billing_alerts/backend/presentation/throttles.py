from typing import Any

from rest_framework.request import Request

from posthog.rate_limit import PersonalApiKeyOrUserRateThrottle


class BillingAlertCheckNowThrottle(PersonalApiKeyOrUserRateThrottle):
    """Limit manual billing evaluations across every caller in an organization."""

    scope = "billing_alert_check_now"
    rate = "10/minute"

    def get_cache_key(self, request: Request, view: Any) -> str | None:
        organization_id = self.safely_get_organization_id_from_view(view)
        if organization_id:
            return self.cache_format % {"scope": self.scope, "ident": f"organization_{organization_id}"}
        return super().get_cache_key(request, view)
