from typing import Any, Optional

from django.conf import settings

from peopledatalabs import PDLPY

PDL_MIN_LIKELIHOOD = 4


class PDLClient:
    """Synchronous People Data Labs person-enrichment wrapper.

    Thin shim around the official `peopledatalabs.PDLPY` SDK that only handles
    person enrichment by email or name. The SDK is synchronous, so callers from
    async contexts should wrap calls with `asyncio.to_thread`.
    """

    def __init__(self) -> None:
        if not settings.PDL_API_KEY:
            raise ValueError("Missing PDL API key: PDL_API_KEY")
        self._client = PDLPY(api_key=settings.PDL_API_KEY)

    def enrich_by_email(self, email: str) -> Optional[dict[str, Any]]:
        return self._enrich({"email": email})

    def enrich_by_name_and_company(self, name: str, company: str) -> Optional[dict[str, Any]]:
        """PDL's enrich endpoint requires a strong identifier; name on its own
        returns 400. Pair it with company (e.g. the email domain) to disambiguate."""
        return self._enrich({"name": name, "company": company})

    def _enrich(self, params: dict[str, Any]) -> Optional[dict[str, Any]]:
        params = {**params, "min_likelihood": PDL_MIN_LIKELIHOOD}
        response = self._client.person.enrichment(**params)
        # 400 → unusable query, 404 → no match, 402 → out of credits, 429 → rate
        # limited. None of these are actionable per-request; surface them all as
        # `None` so the caller falls back to the next provider cleanly.
        if response.status_code in (400, 402, 404, 429):
            return None
        response.raise_for_status()
        return response.json().get("data")
