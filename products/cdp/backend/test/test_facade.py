from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.team import Team

from products.cdp.backend.facade.api import (
    has_distinct_id_hashing_transformation,
    warehouse_tables_with_enabled_hog_functions,
)
from products.cdp.backend.models.hog_functions import HogFunction

VIEW_SOURCE = "data-warehouse-view"


class TestWarehouseTablesWithEnabledHogFunctions(BaseTest):
    def _function(self, source: str, table_names: list[str], *, enabled: bool = True, deleted: bool = False) -> None:
        HogFunction.objects.create(
            team=self.team,
            enabled=enabled,
            deleted=deleted,
            filters={"source": source, "data_warehouse": [{"table_name": name} for name in table_names]},
        )

    def test_returns_only_the_asked_names_an_enabled_function_of_that_source_triggers_on(self) -> None:
        self._function(VIEW_SOURCE, ["orders", "refunds", "not_asked"])
        self._function(VIEW_SOURCE, ["invoices"])
        self._function(VIEW_SOURCE, ["disabled_view"], enabled=False)
        self._function(VIEW_SOURCE, ["deleted_view"], deleted=True)
        self._function("data-warehouse-table", ["table_source"])

        triggered = warehouse_tables_with_enabled_hog_functions(
            team_id=self.team.pk,
            trigger_source=VIEW_SOURCE,
            table_names=["orders", "refunds", "invoices", "disabled_view", "deleted_view", "table_source", "unused"],
        )

        assert triggered == {"orders", "refunds", "invoices"}


PII_HASHING = "template-pii-hashing"
HASH_PROPERTIES = "template-hash-properties"
TEMPLATE_SOURCE = {
    PII_HASHING: "returnEvent.distinct_id := sha256Hex(concat(toString(event.distinct_id), salt))",
    HASH_PROPERTIES: "anonymizedEvent[trimmedFieldName] := hashValue(event[trimmedFieldName], inputs.salt)",
}
CUSTOMIZED_SOURCE = "return event"


class TestHasDistinctIdHashingTransformation(BaseTest):
    def _transformation(
        self,
        template_id: str,
        inputs: dict,
        *,
        team=None,
        enabled: bool = True,
        deleted: bool = False,
        hog: str | None = None,
    ) -> None:
        HogFunction.objects.create(
            team=team or self.team,
            type="transformation",
            template_id=template_id,
            hog=hog if hog is not None else TEMPLATE_SOURCE.get(template_id, CUSTOMIZED_SOURCE),
            enabled=enabled,
            deleted=deleted,
            inputs_schema=[
                {"key": key, "type": "boolean" if isinstance(value, bool) else "string", "secret": False}
                for key, value in inputs.items()
            ],
            inputs={key: {"value": value} for key, value in inputs.items()},
        )

    @parameterized.expand(
        [
            ("pii_hashing_with_distinct_id", PII_HASHING, {"hashDistinctId": True}, {}, True),
            ("pii_hashing_without_distinct_id", PII_HASHING, {"hashDistinctId": False}, {}, False),
            ("pii_hashing_with_no_choice_made", PII_HASHING, {"propertiesToHash": "$ip"}, {}, False),
            ("hash_properties_default_fields", HASH_PROPERTIES, {"privateFields": "distinct_id,name,email"}, {}, True),
            ("hash_properties_spaced_fields", HASH_PROPERTIES, {"privateFields": "email, distinct_id "}, {}, True),
            (
                "hash_properties_without_distinct_id",
                HASH_PROPERTIES,
                {"privateFields": "email,user_distinct_id"},
                {},
                False,
            ),
            ("disabled", PII_HASHING, {"hashDistinctId": True}, {"enabled": False}, False),
            ("deleted", PII_HASHING, {"hashDistinctId": True}, {"deleted": True}, False),
            ("other_template", "template-geoip", {"hashDistinctId": True}, {}, False),
            (
                "pii_hashing_customized_source",
                PII_HASHING,
                {"hashDistinctId": True},
                {"hog": CUSTOMIZED_SOURCE},
                False,
            ),
            (
                "hash_properties_customized_source",
                HASH_PROPERTIES,
                {"privateFields": "distinct_id,email"},
                {"hog": CUSTOMIZED_SOURCE},
                False,
            ),
        ]
    )
    def test_detects_an_enabled_transformation_that_hashes_distinct_id(
        self, _name: str, template_id: str, inputs: dict, state: dict, expected: bool
    ) -> None:
        self._transformation(template_id, inputs, **state)

        assert has_distinct_id_hashing_transformation(team_id=self.team.pk) is expected

    def test_ignores_another_teams_transformation(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        self._transformation(PII_HASHING, {"hashDistinctId": True}, team=other_team)

        assert has_distinct_id_hashing_transformation(team_id=self.team.pk) is False
