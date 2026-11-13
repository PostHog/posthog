from posthog.test.base import BaseTest
from unittest.mock import patch

from django.contrib import admin
from django.test import RequestFactory, SimpleTestCase

from parameterized import parameterized

from posthog.admin.admins.event_ingestion_restriction_config import (
    EventIngestionRestrictionConfigAdmin,
    EventIngestionRestrictionConfigForm,
)
from posthog.models.event_ingestion_restriction_config import EventIngestionRestrictionConfig, RestrictionType
from posthog.models.tophog.restrictions import (
    RESTRICTION_FILTER_FIELDS,
    extend_restriction,
    key_token,
    map_pipelines,
    resolve_team_tokens,
    restriction_matches,
)


class TestTopHogRestrictionMatching(SimpleTestCase):
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
        self.assertEqual(key_token(key, {"1": "resolved"}), expected)

    def test_prefill_params_are_restriction_form_fields(self):
        form_fields = EventIngestionRestrictionConfigForm().fields
        for form_field in ["token", "pipelines", *RESTRICTION_FILTER_FIELDS.values()]:
            self.assertIn(form_field, form_fields)

    @parameterized.expand(
        [
            ("known_names_mapped", ["sessionreplay", "analytics"], ["analytics", "session_recordings"]),
            ("heatmaps_and_ai_mapped", ["heatmaps", "ai"], ["ai", "heatmaps"]),
            ("unknown_names_dropped", ["unknown"], []),
        ]
    )
    def test_map_pipelines(self, _name, tophog_pipelines, expected):
        self.assertEqual(map_pipelines(tophog_pipelines), expected)

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
            ("pipeline_covered", {}, {}, ["analytics"], True),
            ("pipeline_disjoint", {"pipelines": ["errortracking"]}, {}, ["analytics"], False),
            ("unmapped_pipeline_never_covered", {}, {}, ["unknown"], False),
            ("partially_unmapped_never_covered", {}, {}, ["analytics", "unknown"], False),
            ("partial_pipeline_coverage_not_covered", {}, {}, ["analytics", "sessionreplay"], False),
            (
                "full_pipeline_coverage",
                {"pipelines": ["analytics", "session_recordings"]},
                {},
                ["analytics", "sessionreplay"],
                True,
            ),
        ]
    )
    def test_restriction_matches(self, _name, config_kwargs, key, tophog_pipelines, expected):
        restriction = EventIngestionRestrictionConfig(
            token="phc_abc",
            restriction_type=RestrictionType.DROP_EVENT_FROM_INGESTION,
            **{"pipelines": ["analytics"], **config_kwargs},
        )
        self.assertEqual(restriction_matches(restriction, key, tophog_pipelines), expected)

    def test_pipelines_prefill_split_from_comma_separated_param(self):
        model_admin = EventIngestionRestrictionConfigAdmin(EventIngestionRestrictionConfig, admin.site)
        request = RequestFactory().get("/", {"token": "phc_x", "pipelines": "analytics,session_recordings"})
        initial = model_admin.get_changeform_initial_data(request)
        self.assertEqual(initial["pipelines"], ["analytics", "session_recordings"])
        self.assertEqual(initial["token"], "phc_x")


class TestTopHogRestrictionWrites(BaseTest):
    def test_resolve_team_tokens_maps_team_id_to_api_token(self):
        tokens = resolve_team_tokens(
            [
                {"team_id": str(self.team.id), "distinct_id": "did"},
                {"team_id": "not-a-number"},
                {"fn": "process"},
            ]
        )
        self.assertEqual(tokens, {str(self.team.id): self.team.api_token})

    def test_extend_restriction_appends_only_to_nonempty_lists(self):
        restriction = EventIngestionRestrictionConfig.objects.create(
            token="phc_extend",
            restriction_type=RestrictionType.DROP_EVENT_FROM_INGESTION,
            distinct_ids=["existing"],
        )
        with (
            patch("posthog.models.tophog.restrictions.regenerate_redis_for_restriction_type") as regenerate,
            self.captureOnCommitCallbacks(execute=True),
        ):
            changed = extend_restriction(restriction, {"distinct_id": "new-id", "session_id": "s1"})
            # The cache rebuild waits for the commit, so it reads every committed extension.
            regenerate.assert_not_called()
        self.assertEqual(changed, ["distinct_ids"])
        regenerate.assert_called_once_with(RestrictionType.DROP_EVENT_FROM_INGESTION)
        restriction.refresh_from_db()
        self.assertEqual(restriction.distinct_ids, ["existing", "new-id"])
        self.assertEqual(restriction.session_ids, [])

    def test_extend_restriction_noop_when_already_covered(self):
        restriction = EventIngestionRestrictionConfig.objects.create(
            token="phc_noop",
            restriction_type=RestrictionType.DROP_EVENT_FROM_INGESTION,
            distinct_ids=["d1"],
        )
        self.assertEqual(extend_restriction(restriction, {"distinct_id": "d1"}), [])
        restriction.refresh_from_db()
        self.assertEqual(restriction.distinct_ids, ["d1"])
