from urllib.parse import parse_qs, urlparse

from posthog.test.base import BaseTest

from django.urls import reverse

from parameterized import parameterized

from posthog.admin.admins.event_ingestion_restriction_config import EventIngestionRestrictionConfigForm
from posthog.admin.admins.tophog_admin import (
    RESTRICTION_PREFILL_FIELDS,
    _key_token,
    _resolve_team_tokens,
    _restriction_url,
)


class TestTopHogAdminHelpers(BaseTest):
    def test_resolve_team_tokens_maps_team_id_to_api_token(self):
        tokens = _resolve_team_tokens(
            [
                {"team_id": str(self.team.id), "distinct_id": "did"},
                {"team_id": "not-a-number"},
                {"fn": "process"},
            ]
        )
        self.assertEqual(tokens, {str(self.team.id): self.team.api_token})

    @parameterized.expand(
        [
            ("explicit_token", {"token": "phc_abc", "team_id": "1"}, "phc_abc"),
            ("unknown_placeholder_falls_back_to_team_id", {"token": "unknown", "team_id": "1"}, "resolved"),
            ("team_id_lookup", {"team_id": "1"}, "resolved"),
            ("unresolvable_team_id", {"team_id": "2"}, ""),
            ("no_token_or_team_id", {"fn": "process"}, ""),
        ]
    )
    def test_key_token(self, _name, key, expected):
        self.assertEqual(_key_token(key, {"1": "resolved"}), expected)

    def test_restriction_url_prefills_add_form_from_key(self):
        url = _restriction_url(
            "phc_abc",
            {"team_id": "1", "distinct_id": "did", "session_id": "sid", "partition": "3"},
        )
        parsed = urlparse(url)
        self.assertEqual(parsed.path, reverse("admin:posthog_eventingestionrestrictionconfig_add"))
        self.assertEqual(
            parse_qs(parsed.query),
            {"token": ["phc_abc"], "distinct_ids": ["did"], "session_ids": ["sid"]},
        )

    def test_prefill_params_are_restriction_form_fields(self):
        form_fields = EventIngestionRestrictionConfigForm().fields
        for form_field in ["token", *RESTRICTION_PREFILL_FIELDS.values()]:
            self.assertIn(form_field, form_fields)
