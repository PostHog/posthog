from urllib.parse import parse_qs, urlparse

from posthog.test.base import BaseTest

from django.contrib import admin
from django.test import RequestFactory
from django.urls import reverse

from parameterized import parameterized

from posthog.admin.admins.event_ingestion_restriction_config import (
    EventIngestionRestrictionConfigAdmin,
    EventIngestionRestrictionConfigForm,
)
from posthog.admin.admins.tophog_admin import (
    RESTRICTION_FILTER_FIELDS,
    _create_restriction_url,
    _extend_restriction,
    _key_token,
    _map_pipelines,
    _resolve_team_tokens,
    _restriction_matches,
    _restrictions_page_url,
)
from posthog.models.event_ingestion_restriction_config import EventIngestionRestrictionConfig, RestrictionType


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

    def test_restrictions_page_url_carries_full_key_and_pipelines(self):
        url = _restrictions_page_url(
            "phc_abc",
            {"team_id": "1", "distinct_id": "did", "partition": "3", "token": "unknown"},
            ["analytics", "heatmaps"],
        )
        parsed = urlparse(url)
        self.assertEqual(parsed.path, reverse("tophog-restrictions"))
        self.assertEqual(
            parse_qs(parsed.query),
            {
                "token": ["phc_abc"],
                "team_id": ["1"],
                "distinct_id": ["did"],
                "partition": ["3"],
                "pipelines": ["analytics,heatmaps"],
            },
        )

    def test_create_restriction_url_prefills_add_form_from_key(self):
        url = _create_restriction_url(
            "phc_abc",
            {"team_id": "1", "distinct_id": "did", "session_id": "sid", "partition": "3"},
            ["analytics", "session_recordings"],
        )
        parsed = urlparse(url)
        self.assertEqual(parsed.path, reverse("admin:posthog_eventingestionrestrictionconfig_add"))
        self.assertEqual(
            parse_qs(parsed.query),
            {
                "token": ["phc_abc"],
                "distinct_ids": ["did"],
                "session_ids": ["sid"],
                "pipelines": ["analytics,session_recordings"],
            },
        )

    def test_prefill_params_are_restriction_form_fields(self):
        form_fields = EventIngestionRestrictionConfigForm().fields
        for form_field in ["token", "pipelines", *RESTRICTION_FILTER_FIELDS.values()]:
            self.assertIn(form_field, form_fields)

    @parameterized.expand(
        [
            ("known_names_mapped", ["sessionreplay", "analytics"], ["analytics", "session_recordings"]),
            ("unknown_names_dropped", ["heatmaps", "ai"], []),
        ]
    )
    def test_map_pipelines(self, _name, tophog_pipelines, expected):
        self.assertEqual(_map_pipelines(tophog_pipelines), expected)

    @parameterized.expand(
        [
            ("empty_filters_cover_everything", {}, {"distinct_id": "d1"}, [], True),
            ("value_in_list", {"distinct_ids": ["d1", "d2"]}, {"distinct_id": "d1"}, [], True),
            ("value_not_in_list", {"distinct_ids": ["d2"]}, {"distinct_id": "d1"}, [], False),
            (
                "all_fields_must_cover",
                {"distinct_ids": ["d1"], "session_ids": ["s2"]},
                {"distinct_id": "d1", "session_id": "s1"},
                [],
                False,
            ),
            ("pipeline_overlap", {}, {}, ["analytics", "session_recordings"], True),
            ("pipeline_disjoint", {"pipelines": ["errortracking"]}, {}, ["analytics"], False),
        ]
    )
    def test_restriction_matches(self, _name, config_kwargs, key, restriction_pipelines, expected):
        restriction = EventIngestionRestrictionConfig(
            token="phc_abc",
            restriction_type=RestrictionType.DROP_EVENT_FROM_INGESTION,
            **{"pipelines": ["analytics"], **config_kwargs},
        )
        self.assertEqual(_restriction_matches(restriction, key, restriction_pipelines), expected)

    def test_extend_restriction_appends_only_to_nonempty_lists(self):
        restriction = EventIngestionRestrictionConfig.objects.create(
            token="phc_extend",
            restriction_type=RestrictionType.DROP_EVENT_FROM_INGESTION,
            distinct_ids=["existing"],
        )
        changed = _extend_restriction(restriction, {"distinct_id": "new-id", "session_id": "s1"})
        self.assertEqual(changed, ["distinct_ids"])
        restriction.refresh_from_db()
        self.assertEqual(restriction.distinct_ids, ["existing", "new-id"])
        self.assertEqual(restriction.session_ids, [])

    def test_extend_restriction_noop_when_already_covered(self):
        restriction = EventIngestionRestrictionConfig.objects.create(
            token="phc_noop",
            restriction_type=RestrictionType.DROP_EVENT_FROM_INGESTION,
            distinct_ids=["d1"],
        )
        self.assertEqual(_extend_restriction(restriction, {"distinct_id": "d1"}), [])
        restriction.refresh_from_db()
        self.assertEqual(restriction.distinct_ids, ["d1"])

    def test_pipelines_prefill_split_from_comma_separated_param(self):
        model_admin = EventIngestionRestrictionConfigAdmin(EventIngestionRestrictionConfig, admin.site)
        request = RequestFactory().get("/", {"token": "phc_x", "pipelines": "analytics,session_recordings"})
        initial = model_admin.get_changeform_initial_data(request)
        self.assertEqual(initial["pipelines"], ["analytics", "session_recordings"])
        self.assertEqual(initial["token"], "phc_x")

    def test_restrictions_view_extend_post(self):
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)
        restriction = EventIngestionRestrictionConfig.objects.create(
            token="phc_view",
            restriction_type=RestrictionType.DROP_EVENT_FROM_INGESTION,
            distinct_ids=["existing"],
        )
        url = reverse("tophog-restrictions") + "?token=phc_view&distinct_id=new-id"
        response = self.client.post(url, {"restriction_id": str(restriction.pk)})
        self.assertEqual(response.status_code, 302)
        restriction.refresh_from_db()
        self.assertEqual(restriction.distinct_ids, ["existing", "new-id"])
