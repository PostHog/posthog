from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.autoresearch.backend.training.explanation import MAX_TOP_FEATURES, normalize_model_explanation


class TestNormalizeModelExplanation(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "typed_shape",
                {"method": "m", "top_features": [{"name": "a", "importance": 0.2, "direction": "positive"}]},
                {"method": "m", "top_features": [{"name": "a", "importance": 0.2, "direction": "positive"}]},
            ),
            (
                "legacy_features_key_and_arrow_prose",
                {
                    "features": [
                        {"feature": "a", "importance": 0.01, "direction": "higher -> less likely"},
                        {"feature": "b", "importance": 0.05, "direction": "higher = more likely"},
                    ]
                },
                {
                    "top_features": [
                        {"name": "b", "importance": 0.05, "direction": "positive"},
                        {"name": "a", "importance": 0.01, "direction": "negative"},
                    ]
                },
            ),
            (
                "prose_read_per_clause",
                {
                    "top_features": [
                        {"name": "a", "importance": 0.3, "direction": "higher -> less likely; lower -> more likely"},
                        {"name": "b", "importance": 0.2, "direction": "more likely at lower values"},
                        {"name": "c", "importance": 0.1, "direction": "higher -> more likely; lower -> more likely"},
                    ]
                },
                {
                    "top_features": [
                        {"name": "a", "importance": 0.3, "direction": "negative"},
                        {"name": "b", "importance": 0.2, "direction": "negative"},
                    ]
                },
            ),
            (
                "legacy_feature_importances_key_and_signs",
                {
                    "feature_importances": [
                        {"feature": "a", "importance": 0.3, "direction": "down"},
                        {"feature": "b", "auc_drop_when_shuffled": 0.2, "direction": "+"},
                    ]
                },
                {
                    "top_features": [
                        {"name": "a", "importance": 0.3, "direction": "negative"},
                        {"name": "b", "importance": 0.2, "direction": "positive"},
                    ]
                },
            ),
            (
                "unreadable_entries_dropped",
                {
                    "top_features": [
                        "a",
                        {"name": "b", "importance": 0.1, "direction": "sideways"},
                        {"name": "c", "direction": "positive"},
                        {"name": "d", "importance": 0.1, "direction": "lowers"},
                    ]
                },
                {"top_features": [{"name": "d", "importance": 0.1, "direction": "negative"}]},
            ),
            ("not_an_object", ["a"], {"top_features": []}),
            ("empty", {}, {"top_features": []}),
        ]
    )
    def test_normalizes(self, _name: str, raw: Any, expected: dict[str, Any]) -> None:
        assert normalize_model_explanation(raw) == expected

    def test_caps_the_feature_count(self) -> None:
        raw = {"top_features": [{"name": f"f{i}", "importance": i, "direction": "positive"} for i in range(40)]}
        features = normalize_model_explanation(raw)["top_features"]
        assert len(features) == MAX_TOP_FEATURES
        assert features[0]["name"] == "f39"
