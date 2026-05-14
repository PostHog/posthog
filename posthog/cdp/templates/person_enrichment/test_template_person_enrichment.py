from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.person_enrichment.template_person_enrichment import template as template_person_enrichment

PDL_URL_PREFIX = "https://api.peopledatalabs.com/v5/person/enrich"

GOOD_PDL_RESPONSE = {
    "status": 200,
    "body": {
        "data": {
            "full_name": "abhischek thottakara",
            "job_title": "senior software engineer",
            "linkedin_url": "linkedin.com/in/abhischek-thottakara-a6568743",
            # Plan-gated fields surface as boolean sentinels; the template must drop them.
            "work_email": False,
            "personal_emails": True,
            "location_name": True,
            "location_locality": True,
            "location_region": True,
            "location_country": "austria",
            "location_continent": "europe",
        }
    },
}


class TestTemplatePersonEnrichment(BaseHogFunctionTemplateTest):
    template = template_person_enrichment

    def _inputs(self, **kwargs):
        inputs = {"pdl_api_key": "PDL_KEY", "email": "abhischek@posthog.com"}
        inputs.update(kwargs)
        return inputs

    def test_skips_when_email_missing(self):
        result = self.run_function(inputs=self._inputs(email=""))
        assert result.result is False
        assert self.get_mock_fetch_calls() == []

    def test_skips_when_person_already_enriched(self):
        result = self.run_function(
            inputs=self._inputs(),
            globals={"person": {"properties": {"$enriched_at": "2026-05-13T00:00:00Z"}}},
        )
        assert result.result is False
        assert self.get_mock_fetch_calls() == []

    def test_skips_own_set_events_to_avoid_loop(self):
        result = self.run_function(
            inputs=self._inputs(),
            globals={"event": {"event": "$set"}},
        )
        assert result.result is False
        assert self.get_mock_fetch_calls() == []

    def test_emits_set_with_curated_fields_on_match(self):
        self.fetch_responses = {
            "https://api.peopledatalabs.com/v5/person/enrich?email=abhischek@posthog.com&min_likelihood=4": GOOD_PDL_RESPONSE,
        }
        self.run_function(inputs=self._inputs())

        fetch_calls = self.get_mock_fetch_calls()
        assert len(fetch_calls) == 1
        url, options = fetch_calls[0]
        assert url.startswith(PDL_URL_PREFIX)
        assert "email=abhischek@posthog.com" in url
        # API key must be in the header, not the URL query string.
        assert "api_key=" not in url
        assert options == {"method": "GET", "headers": {"X-Api-Key": "PDL_KEY"}}

        capture_calls = self.get_mock_posthog_capture_calls()
        assert len(capture_calls) == 1
        capture_event = capture_calls[0][0]
        assert capture_event["event"] == "$set"
        set_props = capture_event["properties"]["$set"]
        # Sentinel booleans must not leak through to person properties.
        assert "$enriched_professional_email" not in set_props
        assert "$enriched_personal_email" not in set_props
        # Real string fields are preserved as-is.
        assert set_props["$enriched_full_name"] == "abhischek thottakara"
        assert set_props["$enriched_job_title"] == "senior software engineer"
        assert set_props["$enriched_linkedin_url"] == "linkedin.com/in/abhischek-thottakara-a6568743"
        # Location resolves down the priority chain to `location_country`.
        assert set_props["$enriched_location"] == "austria"
        assert "$enriched_at" in set_props

    def test_no_match_when_pdl_404s(self):
        self.fetch_responses = {
            "https://api.peopledatalabs.com/v5/person/enrich?email=abhischek@posthog.com&min_likelihood=4": {
                "status": 404,
                "body": {},
            },
        }
        self.run_function(inputs=self._inputs())
        assert self.get_mock_posthog_capture_calls() == []

    def test_exits_cleanly_on_pdl_402(self):
        self.fetch_responses = {
            "https://api.peopledatalabs.com/v5/person/enrich?email=abhischek@posthog.com&min_likelihood=4": {
                "status": 402,
                "body": {},
            },
        }
        self.run_function(inputs=self._inputs())
        assert self.get_mock_posthog_capture_calls() == []
