from django.test.testcases import SimpleTestCase

from parameterized import parameterized
from pydantic import ValidationError

from posthog.schema import FunnelsQuery


class TestFunnelsSeriesDiscriminator(SimpleTestCase):
    # `FunnelsQuery.series` was an undiscriminated union — Pydantic would walk every
    # variant and report errors for each, so a single malformed series item produced
    # a dozen-plus errors per item (hundreds for real-world malformed queries), and
    # items missing `kind` silently coerced to EventsNode. These tests pin the `kind`
    # discriminator so a schema regeneration that drops it (generator config change,
    # patch-script miss in bin/patch-schema-array-discriminators.py) fails here.

    _ALL_KINDS = ("EventsNode", "ActionsNode", "FunnelsDataWarehouseNode", "GroupNode")

    @staticmethod
    def _query(series: list[dict]) -> dict:
        return {"kind": "FunnelsQuery", "series": series}

    @parameterized.expand(
        [
            # (case_name, series_item, declared_kind)
            ("events_node_extra_field", {"kind": "EventsNode", "event": "$pageview", "id": 5}, "EventsNode"),
            ("actions_node_bad_id", {"kind": "ActionsNode", "id": "not-an-int"}, "ActionsNode"),
            ("group_node_missing_required", {"kind": "GroupNode"}, "GroupNode"),
            ("data_warehouse_node_missing_required", {"kind": "FunnelsDataWarehouseNode"}, "FunnelsDataWarehouseNode"),
        ]
    )
    def test_invalid_item_routes_to_declared_kind_only(self, _name: str, series_item: dict, declared_kind: str) -> None:
        with self.assertRaises(ValidationError) as ctx:
            FunnelsQuery.model_validate(self._query([series_item]))

        errors = ctx.exception.errors()
        assert errors, "expected at least one validation error"

        item_errors = [err for err in errors if err["loc"][:2] == ("series", 0)]
        assert item_errors, f"expected errors under ('series', 0); got locs {[err['loc'] for err in errors]}"

        kinds_in_locs = {
            err["loc"][2] for err in item_errors if len(err["loc"]) > 2 and err["loc"][2] in self._ALL_KINDS
        }
        assert kinds_in_locs == {declared_kind}, (
            f"errors should reach exactly one variant tag {declared_kind!r}; "
            f"got {kinds_in_locs!r} — series discriminator likely dropped"
        )

    @parameterized.expand(
        [
            # Positive routing proof: fields REQUIRED by the declared variant are reported
            # missing — an undiscriminated union would drown these in other variants' noise.
            ("group_node", "GroupNode", {"operator", "nodes"}),
            (
                "data_warehouse_node",
                "FunnelsDataWarehouseNode",
                {"id", "id_field", "table_name", "timestamp_field", "aggregation_target_field"},
            ),
        ]
    )
    def test_missing_required_fields_reported_for_declared_kind(
        self, _name: str, declared_kind: str, expected_missing: set[str]
    ) -> None:
        with self.assertRaises(ValidationError) as ctx:
            FunnelsQuery.model_validate(self._query([{"kind": declared_kind}]))

        errors = ctx.exception.errors()
        missing = {
            err["loc"][3]
            for err in errors
            if err["type"] == "missing" and err["loc"][:3] == ("series", 0, declared_kind)
        }
        assert missing == expected_missing, f"expected missing fields {expected_missing!r}, got {missing!r}"
        assert len(errors) == len(expected_missing), f"expected only missing-field errors, got {errors}"

    def test_unknown_kind_returns_single_clean_tag_error(self) -> None:
        with self.assertRaises(ValidationError) as ctx:
            FunnelsQuery.model_validate(self._query([{"kind": "banana", "event": "$pageview"}]))

        errors = ctx.exception.errors()
        assert len(errors) == 1, f"expected exactly one error, got {len(errors)}: {errors}"
        assert errors[0]["type"] == "union_tag_invalid"
        expected_tags_str = errors[0]["ctx"]["expected_tags"]
        for tag in self._ALL_KINDS:
            assert f"'{tag}'" in expected_tags_str, f"expected tag {tag!r} in {expected_tags_str!r}"

    def test_missing_kind_returns_one_error_per_item(self) -> None:
        # Regression for the error explosion this discriminator fixes: three malformed
        # items must produce exactly three errors, not one per (item x variant x field).
        with self.assertRaises(ValidationError) as ctx:
            FunnelsQuery.model_validate(self._query([{"event": "a"}, {"event": "b"}, {"event": "c"}]))

        errors = ctx.exception.errors()
        assert len(errors) == 3, f"expected exactly one error per series item, got {len(errors)}: {errors}"
        assert all(err["type"] == "union_tag_not_found" for err in errors)

    @parameterized.expand(
        [
            ("events_node", {"kind": "EventsNode", "event": "$pageview"}),
            ("actions_node", {"kind": "ActionsNode", "id": 1}),
            (
                "group_node",
                {"kind": "GroupNode", "operator": "AND", "nodes": [{"kind": "EventsNode", "event": "$pageview"}]},
            ),
            (
                "data_warehouse_node",
                {
                    "kind": "FunnelsDataWarehouseNode",
                    "id": "orders",
                    "id_field": "id",
                    "table_name": "orders",
                    "timestamp_field": "created_at",
                    "aggregation_target_field": "user_id",
                },
            ),
        ]
    )
    def test_valid_item_per_kind_still_validates(self, _name: str, series_item: dict) -> None:
        FunnelsQuery.model_validate(self._query([series_item]))
