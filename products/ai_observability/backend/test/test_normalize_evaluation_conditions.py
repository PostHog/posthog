import importlib

from parameterized import parameterized

_migration = importlib.import_module(
    "products.ai_observability.backend.migrations.0003_normalize_evaluation_conditions"
)
_normalize_condition = _migration._normalize_condition
_conditions_need_fix = _migration._conditions_need_fix


class TestNormalizeEvaluationConditions:
    def test_drops_stray_keys_and_defaults_missing_rollout_to_zero(self):
        result = _normalize_condition({"id": "cond-1", "sampling_rate": 50, "properties": []})
        assert result == {"id": "cond-1", "rollout_percentage": 0, "properties": []}

    def test_backfills_missing_id(self):
        result = _normalize_condition({"rollout_percentage": 100, "properties": []})
        assert isinstance(result["id"], str) and result["id"]
        assert result["rollout_percentage"] == 100
        assert result["properties"] == []

    def test_folds_top_level_property_filter_into_properties(self):
        result = _normalize_condition(
            {"id": "c1", "key": "$ai_model", "value": "gpt-4", "operator": "exact", "type": "event"}
        )
        assert result["id"] == "c1"
        assert result["rollout_percentage"] == 0
        assert result["properties"] == [{"key": "$ai_model", "value": "gpt-4", "operator": "exact", "type": "event"}]

    def test_folds_top_level_filter_after_existing_properties(self):
        result = _normalize_condition(
            {"id": "c1", "rollout_percentage": 25, "properties": [{"key": "a"}], "key": "b", "operator": "exact"}
        )
        assert result["properties"] == [{"key": "a"}, {"key": "b", "operator": "exact"}]
        assert result["rollout_percentage"] == 25

    def test_normalizes_bool_rollout_to_zero(self):
        assert (
            _normalize_condition({"id": "c1", "rollout_percentage": True, "properties": []})["rollout_percentage"] == 0
        )

    def test_drops_non_dict_property_members(self):
        result = _normalize_condition({"id": "c1", "rollout_percentage": 0, "properties": ["garbage", {"key": "k"}]})
        assert result["properties"] == [{"key": "k"}]

    def test_normalized_output_is_idempotent(self):
        dirty = [{"id": "c1", "sampling_rate": 1, "key": "k", "value": "v"}]
        once = [_normalize_condition(condition) for condition in dirty]
        assert _conditions_need_fix(once) is False
        assert [_normalize_condition(condition) for condition in once] == once

    def test_leaves_already_valid_condition_unchanged(self):
        condition = {
            "id": "c1",
            "rollout_percentage": 50,
            "properties": [{"key": "x", "value": "y", "operator": "exact", "type": "event"}],
        }
        assert _normalize_condition(condition) == condition

    def test_preserves_bytecode_when_properties_unchanged(self):
        condition = {
            "id": "c1",
            "sampling_rate": 10,
            "properties": [{"key": "x", "value": "y", "operator": "exact", "type": "event"}],
            "bytecode": ["_H", 1],
            "bytecode_error": None,
        }
        result = _normalize_condition(condition)
        assert result["bytecode"] == ["_H", 1]
        assert result["bytecode_error"] is None
        assert "sampling_rate" not in result
        assert result["rollout_percentage"] == 0

    def test_drops_stale_bytecode_when_folding_changes_properties(self):
        result = _normalize_condition(
            {"id": "c1", "key": "x", "value": "y", "operator": "exact", "type": "event", "bytecode": ["_H", 1]}
        )
        assert "bytecode" not in result
        assert result["properties"] == [{"key": "x", "value": "y", "operator": "exact", "type": "event"}]

    def test_handles_non_dict_condition(self):
        result = _normalize_condition("garbage")
        assert isinstance(result["id"], str) and result["id"]
        assert result["rollout_percentage"] == 0
        assert result["properties"] == []

    @parameterized.expand(
        [
            ("stray_key", [{"id": "c1", "sampling_rate": 1, "properties": []}]),
            ("missing_id", [{"rollout_percentage": 100, "properties": []}]),
            ("leaked_filter_key", [{"id": "c1", "key": "x"}]),
            ("missing_rollout", [{"id": "c1", "properties": []}]),
            ("bool_rollout", [{"id": "c1", "rollout_percentage": True, "properties": []}]),
            ("non_dict_property_member", [{"id": "c1", "rollout_percentage": 0, "properties": ["garbage"]}]),
            ("not_a_list", "not a list"),
            ("non_dict_member", ["garbage"]),
        ]
    )
    def test_conditions_need_fix_true(self, _name, conditions):
        assert _conditions_need_fix(conditions) is True

    @parameterized.expand(
        [
            ("empty", []),
            ("canonical", [{"id": "c1", "rollout_percentage": 100, "properties": []}]),
            (
                "canonical_with_bytecode",
                [{"id": "c1", "rollout_percentage": 50, "properties": [], "bytecode": ["_H"], "bytecode_error": None}],
            ),
        ]
    )
    def test_conditions_need_fix_false(self, _name, conditions):
        assert _conditions_need_fix(conditions) is False
