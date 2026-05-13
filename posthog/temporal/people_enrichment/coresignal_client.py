from typing import Any, Optional

from django.conf import settings

import requests

CORESIGNAL_REQUEST_TIMEOUT_SECONDS = 30


class CoreSignalClient:
    """Synchronous CoreSignal employee-search wrapper.

    CoreSignal's API is a two-step lookup:
    1. POST `/employee_multi_source/search/es_dsl` with an Elasticsearch DSL
       query → returns a list of candidate employee IDs.
    2. GET `/employee_multi_source/collect/{id}` → returns the full profile.

    For person enrichment we run a name match, take the first ID, and collect it.
    """

    def __init__(self) -> None:
        if not settings.CORESIGNAL_API_KEY:
            raise ValueError("Missing CoreSignal API key: CORESIGNAL_API_KEY")
        self._api_key = settings.CORESIGNAL_API_KEY
        self._base_url = settings.CORESIGNAL_BASE_URL

    def _headers(self) -> dict[str, str]:
        return {
            "apikey": self._api_key,
            "accept": "application/json",
            "Content-Type": "application/json",
        }

    def search_by_name(self, full_name: str) -> Optional[int]:
        """Return the top-ranked employee ID for an exact full-name match, or None."""
        return self._search(
            {
                "query": {
                    "match": {
                        "full_name": {
                            "query": full_name,
                            "operator": "and",
                        }
                    }
                }
            }
        )

    def search_by_name_and_active_employer(self, full_name: str, employer_brand: str) -> Optional[int]:
        """Find a person by name whose *current* employer's name matches a brand
        (typically the first label of an email domain — e.g. `impact.com` → `impact`).

        CoreSignal's `experience.company_website` field doesn't appear to be queryable
        via ES DSL (probes return 0 hits across `match`/`match_phrase`/`term`/`wildcard`),
        but `experience.company_name` works inside a nested query. Requiring
        `active_experience == 1` ensures we only match if the brand appears in the
        candidate's current role, which collapses the same-name ambiguity drastically."""
        return self._search(
            {
                "query": {
                    "bool": {
                        "must": [
                            {"match": {"full_name": {"query": full_name, "operator": "and"}}},
                            {
                                "nested": {
                                    "path": "experience",
                                    "query": {
                                        "bool": {
                                            "must": [
                                                {"match": {"experience.company_name": employer_brand}},
                                                {"term": {"experience.active_experience": 1}},
                                            ]
                                        }
                                    },
                                }
                            },
                        ]
                    }
                }
            }
        )

    def _search(self, body: dict[str, Any]) -> Optional[int]:
        response = requests.post(
            f"{self._base_url}/employee_multi_source/search/es_dsl",
            headers=self._headers(),
            json=body,
            timeout=CORESIGNAL_REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code in (400, 402, 404, 429):
            return None
        response.raise_for_status()
        ids = response.json()
        if not isinstance(ids, list) or not ids:
            return None
        return ids[0]

    def collect(self, employee_id: int) -> Optional[dict[str, Any]]:
        response = requests.get(
            f"{self._base_url}/employee_multi_source/collect/{employee_id}",
            headers=self._headers(),
            timeout=CORESIGNAL_REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def enrich_by_name(self, full_name: str) -> Optional[dict[str, Any]]:
        employee_id = self.search_by_name(full_name)
        if employee_id is None:
            return None
        return self.collect(employee_id)

    def enrich_by_name_and_active_employer(self, full_name: str, employer_brand: str) -> Optional[dict[str, Any]]:
        """Search constrained by name AND active employer brand, then collect."""
        employee_id = self.search_by_name_and_active_employer(full_name, employer_brand)
        if employee_id is None:
            return None
        return self.collect(employee_id)
