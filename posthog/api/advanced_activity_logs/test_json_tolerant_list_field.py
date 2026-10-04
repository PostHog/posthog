from django.http import QueryDict
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.api.advanced_activity_logs.viewset import AdvancedActivityLogFiltersSerializer


def _querydict(pairs: list[tuple[str, str]]) -> QueryDict:
    qd = QueryDict(mutable=True)
    for key, value in pairs:
        qd.appendlist(key, value)
    return qd


class TestJSONTolerantListField(SimpleTestCase):
    @parameterized.expand(
        [
            ("json_encoded_array", [("scopes", '["FeatureFlag","Insight"]')], ["FeatureFlag", "Insight"]),
            ("repeated_params", [("scopes", "FeatureFlag"), ("scopes", "Insight")], ["FeatureFlag", "Insight"]),
            ("json_single_element", [("scopes", '["FeatureFlag"]')], ["FeatureFlag"]),
            ("single_plain_value", [("scopes", "FeatureFlag")], ["FeatureFlag"]),
        ]
    )
    def test_scopes_accepts_json_and_repeated(
        self, _name: str, pairs: list[tuple[str, str]], expected: list[str]
    ) -> None:
        serializer = AdvancedActivityLogFiltersSerializer(data=_querydict(pairs))
        serializer.is_valid(raise_exception=True)
        self.assertEqual(serializer.validated_data["scopes"], expected)

    def test_item_ids_accepts_json_encoded_array(self) -> None:
        serializer = AdvancedActivityLogFiltersSerializer(data=_querydict([("item_ids", '["680699","123"]')]))
        serializer.is_valid(raise_exception=True)
        self.assertEqual(serializer.validated_data["item_ids"], ["680699", "123"])
