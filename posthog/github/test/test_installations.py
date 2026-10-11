from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import OperationalError

from posthog.github.installations import installation_integrations, installation_lookup_scope
from posthog.models.integration import Integration
from posthog.models.team.team import Team


class TestInstallationIntegrations(BaseTest):
    def test_a_lookup_outside_a_scope_reads_rows_connected_after_an_earlier_scope(self) -> None:
        first = Integration.objects.create(team=self.team, kind="github", integration_id="4242")

        with installation_lookup_scope():
            self.assertEqual([integration.id for integration in installation_integrations("4242")], [first.id])

        other_team = Team.objects.create(organization=self.organization, name="Second project")
        second = Integration.objects.create(team=other_team, kind="github", integration_id="4242")

        self.assertEqual(
            sorted(integration.id for integration in installation_integrations("4242")), sorted([first.id, second.id])
        )

    def test_a_failed_lookup_is_raised_to_every_caller_in_the_scope_without_querying_again(self) -> None:
        timeout = OperationalError("canceling statement due to statement timeout")

        with (
            patch.object(Integration.objects, "using", side_effect=timeout) as using,
            installation_lookup_scope(),
        ):
            for _ in range(2):
                with self.assertRaises(OperationalError):
                    installation_integrations("4242")

        self.assertEqual(using.call_count, 1)
