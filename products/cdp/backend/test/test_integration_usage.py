from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import Team
from posthog.models.integration import Integration

from products.cdp.backend.models import HogFunction
from products.cdp.backend.services.integration_usage import (
    count_hog_functions_using_integrations,
    extract_integration_ids,
)

INTEGRATION_SCHEMA = [{"key": "slack", "type": "integration"}]


class TestExtractIntegrationIds(SimpleTestCase):
    # The runtime resolves input.value.integrationId ?? input.value — both the deletion guard
    # and the usage sync depend on this extraction handling every stored shape.
    @parameterized.expand(
        [
            ("dict_value", {"slack": {"value": {"integrationId": 7}}}, INTEGRATION_SCHEMA, {7}),
            ("bare_value", {"slack": {"value": 7}}, INTEGRATION_SCHEMA, {7}),
            ("numeric_string_value", {"slack": {"value": "7"}}, INTEGRATION_SCHEMA, {7}),
            ("non_integration_input_ignored", {"slack": {"value": 7}}, [{"key": "slack", "type": "string"}], set()),
            ("non_numeric_value_ignored", {"slack": {"value": "not-an-id"}}, INTEGRATION_SCHEMA, set()),
        ]
    )
    def test_extract_integration_ids(self, _name, inputs, inputs_schema, expected):
        assert extract_integration_ids(inputs, inputs_schema) == expected


class TestHogFunctionIntegrationUsage(BaseTest):
    def setUp(self):
        super().setUp()
        self.integration = Integration.objects.create(team=self.team, kind="slack", config={"team": {"id": "T123"}})

    def _create_function(self, integration_value: object, **kwargs) -> HogFunction:
        return HogFunction.objects.create(
            team=self.team,
            name="Slack notifier",
            type="destination",
            hog="return event",
            enabled=True,
            inputs_schema=INTEGRATION_SCHEMA,
            inputs={"slack": {"value": integration_value}},
            **kwargs,
        )

    def test_save_links_and_unlinks_integrations(self):
        function = self._create_function(self.integration.id)
        assert count_hog_functions_using_integrations(self.team.id, [self.integration.id]) == {self.integration.id: 1}

        function.inputs = {"slack": {"value": None}}
        function.save()
        assert count_hog_functions_using_integrations(self.team.id, [self.integration.id]) == {}

    def test_deleted_functions_are_not_counted(self):
        function = self._create_function(self.integration.id)
        function.deleted = True
        function.save()

        assert count_hog_functions_using_integrations(self.team.id, [self.integration.id]) == {}

    def test_dangling_and_cross_team_references_are_not_linked(self):
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        other_team_integration = Integration.objects.create(team=other_team, kind="slack", config={})
        self._create_function(other_team_integration.id)
        self._create_function(self.integration.id + other_team_integration.id)  # no such integration

        assert (
            count_hog_functions_using_integrations(self.team.id, [self.integration.id, other_team_integration.id]) == {}
        )
