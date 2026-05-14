from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.organization_enrichment.template_organization_enrichment import (
    template as template_organization_enrichment,
)

GOOD_HARMONIC_RESPONSE = {
    "status": 200,
    "body": {
        "data": {
            "enrichCompanyByIdentifiers": {
                "companyFound": True,
                "company": {
                    "name": "PostHog",
                    "website": {"domain": "posthog.com"},
                    "headcount": 65,
                    "description": "Open-source product analytics",
                    "location": {"city": "San Francisco", "state": "California", "country": "United States"},
                    "foundingDate": {"date": "2020-01-01"},
                    "funding": {
                        "fundingTotal": 27000000,
                        "numFundingRounds": 3,
                        "lastFundingAt": "2021-11-09",
                        "lastFundingType": "SERIES_B",
                        "lastFundingTotal": 15000000,
                        "fundingStage": "SERIES_B",
                    },
                    "tractionMetrics": {
                        "webTraffic": {"latestMetricValue": 350000},
                        "linkedinFollowerCount": {"latestMetricValue": 25000},
                        "twitterFollowerCount": {"latestMetricValue": 12000},
                    },
                },
            }
        }
    },
}


def _group_event(domain="posthog.com", already_enriched=False) -> dict:
    """Build a `$groupidentify` event the way the SDK would send it."""
    group_set: dict = {"domain": domain}
    if already_enriched:
        group_set["$enriched_org_name"] = "PostHog"
    return {
        "event": "$groupidentify",
        "properties": {"$group_type": "organization", "$group_key": "org-123", "$group_set": group_set},
    }


class TestTemplateOrganizationEnrichment(BaseHogFunctionTemplateTest):
    template = template_organization_enrichment

    def _inputs(self, **kwargs):
        inputs = {
            "harmonic_api_key": "HK",
            "group_type": "organization",
            "domain": "posthog.com",
            # Query body is irrelevant for these tests since `fetch` is mocked.
            "query": "mutation { _ }",
        }
        inputs.update(kwargs)
        return inputs

    def test_skips_when_group_type_mismatches(self):
        result = self.run_function(
            inputs=self._inputs(),
            globals={
                "event": {
                    "event": "$groupidentify",
                    "properties": {"$group_type": "project", "$group_key": "abc"},
                }
            },
        )
        assert result.result is False
        assert self.get_mock_fetch_calls() == []

    def test_skips_when_event_already_carries_enriched_fields(self):
        result = self.run_function(inputs=self._inputs(), globals={"event": _group_event(already_enriched=True)})
        assert result.result is False
        assert self.get_mock_fetch_calls() == []

    def test_skips_when_domain_missing(self):
        result = self.run_function(inputs=self._inputs(domain=""), globals={"event": _group_event()})
        assert result.result is False
        assert self.get_mock_fetch_calls() == []

    def test_emits_groupidentify_with_curated_fields_on_match(self):
        self.fetch_responses = {"https://api.harmonic.ai/graphql": GOOD_HARMONIC_RESPONSE}
        self.run_function(inputs=self._inputs(), globals={"event": _group_event()})

        fetch_calls = self.get_mock_fetch_calls()
        assert len(fetch_calls) == 1
        url, options = fetch_calls[0]
        assert url == "https://api.harmonic.ai/graphql"
        # API key must travel in the `apikey` header, not the URL query string.
        assert "apikey=" not in url
        assert options["headers"]["apikey"] == "HK"
        assert options["method"] == "POST"
        # Confirm the request body carries the cleaned websiteUrl variable.
        assert options["body"]["variables"] == {"identifiers": {"websiteUrl": "https://posthog.com"}}

        capture_calls = self.get_mock_posthog_capture_calls()
        assert len(capture_calls) == 1
        ev = capture_calls[0][0]
        assert ev["event"] == "$groupidentify"
        props = ev["properties"]
        assert props["$group_type"] == "organization"
        assert props["$group_key"] == "org-123"

        gs = props["$group_set"]
        assert gs["$enriched_org_name"] == "PostHog"
        assert gs["$enriched_org_domain"] == "posthog.com"
        assert gs["$enriched_org_headcount"] == 65
        assert gs["$enriched_org_headquarters"] == "San Francisco, California, United States"
        assert gs["$enriched_org_city"] == "San Francisco"
        assert gs["$enriched_org_state"] == "California"
        assert gs["$enriched_org_country"] == "United States"
        assert gs["$enriched_org_funding_stage"] == "SERIES_B"
        assert gs["$enriched_org_funding_total"] == 27000000
        assert gs["$enriched_org_num_funding_rounds"] == 3
        assert gs["$enriched_org_last_funding_type"] == "SERIES_B"
        assert gs["$enriched_org_founded_year"] == 2020
        assert gs["$enriched_org_linkedin_followers"] == 25000
        assert "$enriched_at" in gs

    def test_stamps_enriched_at_when_company_not_found(self):
        # Confirmed no-match stamps `$enriched_at` on the group so the durable
        # gate blocks future replays for this group key.
        self.fetch_responses = {
            "https://api.harmonic.ai/graphql": {
                "status": 200,
                "body": {"data": {"enrichCompanyByIdentifiers": {"companyFound": False}}},
            },
        }
        self.run_function(inputs=self._inputs(), globals={"event": _group_event()})

        capture_calls = self.get_mock_posthog_capture_calls()
        assert len(capture_calls) == 1
        ev = capture_calls[0][0]
        assert ev["event"] == "$groupidentify"
        assert ev["properties"]["$group_type"] == "organization"
        assert ev["properties"]["$group_key"] == "org-123"
        assert list(ev["properties"]["$group_set"].keys()) == ["$enriched_at"]

    def test_skips_when_group_already_enriched_in_stored_properties(self):
        # Stored `$enriched_at` on the group should block re-enrichment even
        # when the incoming `$group_set` does not carry it.
        result = self.run_function(
            inputs=self._inputs(),
            globals={
                "event": _group_event(),
                "groups": {"organization": {"properties": {"$enriched_at": "2026-05-13T00:00:00Z"}}},
            },
        )
        assert result.result is False
        assert self.get_mock_fetch_calls() == []
