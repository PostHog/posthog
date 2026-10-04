from django.test.testcases import SimpleTestCase

from parameterized import parameterized
from pydantic import BaseModel, ValidationError

from posthog.schema import (
    CalendarHeatmapQuery,
    DataTableNode,
    DetectorConfig,
    FunnelsFilter,
    HogQLMetadata,
    LifecycleQuery,
    StickinessQuery,
    TrendsQuery,
)

# Companion to test_funnels_series_discriminator.py, which pins the detailed error
# shapes of the discriminator mechanism for one site. Each union here was made a
# discriminated union separately (JSDoc @discriminator tag + schema regeneration),
# so each site needs its own canary: `union_tag_invalid` is only ever produced by a
# discriminated union, so these fail if a regeneration drops any single site back
# to undiscriminated validation (error explosion + silent first-member coercion).

_BAD_TAG = {"kind": "banana"}


class TestQuerySchemaDiscriminators(SimpleTestCase):
    @parameterized.expand(
        [
            # (case_name, model, payload, field_with_tagged_union)
            ("trends_series", TrendsQuery, {"kind": "TrendsQuery", "series": [_BAD_TAG]}, "series"),
            ("stickiness_series", StickinessQuery, {"kind": "StickinessQuery", "series": [_BAD_TAG]}, "series"),
            ("lifecycle_series", LifecycleQuery, {"kind": "LifecycleQuery", "series": [_BAD_TAG]}, "series"),
            (
                "calendar_heatmap_series",
                CalendarHeatmapQuery,
                {"kind": "CalendarHeatmapQuery", "series": [_BAD_TAG]},
                "series",
            ),
            ("funnel_exclusions", FunnelsFilter, {"exclusions": [_BAD_TAG]}, "exclusions"),
            ("data_table_source", DataTableNode, {"kind": "DataTableNode", "source": _BAD_TAG}, "source"),
            (
                "hogql_metadata_source_query",
                HogQLMetadata,
                {"kind": "HogQLMetadata", "language": "hogQL", "query": "select 1", "sourceQuery": _BAD_TAG},
                "sourceQuery",
            ),
            ("detector_config_root", DetectorConfig, {"type": "banana"}, None),
            (
                "ensemble_sub_detectors",
                DetectorConfig,
                {"type": "ensemble", "operator": "and", "detectors": [{"type": "banana"}]},
                "detectors",
            ),
        ]
    )
    def test_unknown_tag_returns_single_union_tag_error(
        self, _name: str, model: type[BaseModel], payload: dict, field: str | None
    ) -> None:
        with self.assertRaises(ValidationError) as ctx:
            model.model_validate(payload)

        errors = ctx.exception.errors()
        assert len(errors) == 1, f"expected exactly one error, got {len(errors)}: {errors}"
        assert errors[0]["type"] == "union_tag_invalid", (
            f"expected union_tag_invalid (discriminator likely dropped), got {errors[0]['type']!r}: {errors[0]}"
        )
        if field is not None:
            assert field in errors[0]["loc"], f"expected error under {field!r}, got loc {errors[0]['loc']!r}"

    @parameterized.expand(
        [
            # (case_name, model, payload) — the union member's tag field has a pydantic
            # default, but discriminated unions require the tag in the raw input; these pin
            # the intentional rejection of tag-less payloads (previously silent coercion to
            # the first structurally-matching member).
            ("trends_series", TrendsQuery, {"kind": "TrendsQuery", "series": [{"event": "$pageview"}]}),
            ("stickiness_series", StickinessQuery, {"kind": "StickinessQuery", "series": [{"event": "$pageview"}]}),
            ("lifecycle_series", LifecycleQuery, {"kind": "LifecycleQuery", "series": [{"event": "$pageview"}]}),
            (
                "calendar_heatmap_series",
                CalendarHeatmapQuery,
                {"kind": "CalendarHeatmapQuery", "series": [{"event": "$pageview"}]},
            ),
            (
                "funnel_exclusions",
                FunnelsFilter,
                {"exclusions": [{"event": "$pageview", "funnelFromStep": 0, "funnelToStep": 1}]},
            ),
            ("data_table_source", DataTableNode, {"kind": "DataTableNode", "source": {"query": "select 1"}}),
            (
                "hogql_metadata_source_query",
                HogQLMetadata,
                {"kind": "HogQLMetadata", "language": "hogQL", "query": "select 1", "sourceQuery": {"select": ["*"]}},
            ),
            ("detector_config_root", DetectorConfig, {"threshold": 0.9}),
            (
                "ensemble_sub_detectors",
                DetectorConfig,
                {"type": "ensemble", "operator": "and", "detectors": [{"threshold": 0.9}]},
            ),
        ]
    )
    def test_missing_tag_returns_single_union_tag_error(
        self, _name: str, model: type[BaseModel], payload: dict
    ) -> None:
        with self.assertRaises(ValidationError) as ctx:
            model.model_validate(payload)

        errors = ctx.exception.errors()
        assert len(errors) == 1, f"expected exactly one error, got {len(errors)}: {errors}"
        assert errors[0]["type"] == "union_tag_not_found", (
            f"expected union_tag_not_found (tag-less payload must be rejected, not coerced), got {errors[0]['type']!r}: {errors[0]}"
        )

    @parameterized.expand(
        [
            (
                "trends_series",
                TrendsQuery,
                {
                    "kind": "TrendsQuery",
                    "series": [
                        {"kind": "EventsNode", "event": "$pageview"},
                        {"kind": "GroupNode", "operator": "AND", "nodes": [{"kind": "ActionsNode", "id": 1}]},
                    ],
                },
            ),
            (
                "stickiness_series",
                StickinessQuery,
                {"kind": "StickinessQuery", "series": [{"kind": "ActionsNode", "id": 1}]},
            ),
            (
                "lifecycle_series",
                LifecycleQuery,
                {"kind": "LifecycleQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
            ),
            (
                "calendar_heatmap_series",
                CalendarHeatmapQuery,
                {"kind": "CalendarHeatmapQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
            ),
            (
                "funnel_exclusions",
                FunnelsFilter,
                {"exclusions": [{"kind": "EventsNode", "event": "$pageview", "funnelFromStep": 0, "funnelToStep": 1}]},
            ),
            (
                "data_table_source",
                DataTableNode,
                {"kind": "DataTableNode", "source": {"kind": "HogQLQuery", "query": "select 1"}},
            ),
            (
                "hogql_metadata_source_query",
                HogQLMetadata,
                {
                    "kind": "HogQLMetadata",
                    "language": "hogQL",
                    "query": "select 1",
                    "sourceQuery": {"kind": "EventsQuery", "select": ["*"]},
                },
            ),
            ("detector_config_single", DetectorConfig, {"type": "zscore", "threshold": 0.9}),
            (
                "detector_config_ensemble",
                DetectorConfig,
                {"type": "ensemble", "operator": "and", "detectors": [{"type": "zscore"}, {"type": "mad"}]},
            ),
        ]
    )
    def test_valid_payload_still_validates(self, _name: str, model: type[BaseModel], payload: dict) -> None:
        model.model_validate(payload)
