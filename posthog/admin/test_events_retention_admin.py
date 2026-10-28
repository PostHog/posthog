import time_machine
from posthog.test.base import BaseTest

from django.urls import reverse

from posthog.models.events_retention_config import OrganizationEventsRetentionConfig


class TestEventsRetentionAdmin(BaseTest):
    @time_machine.travel("2026-10-20T12:00:00Z", tick=False)
    def test_page_lists_the_teams_of_an_organization_with_a_default(self) -> None:
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)

        empty = self.client.get(reverse("events-retention"))
        assert empty.status_code == 200
        assert "No team has a deletion retention yet" in empty.content.decode()

        OrganizationEventsRetentionConfig.objects.create(
            organization=self.organization, default_events_retention_months=13
        )
        response = self.client.get(reverse("events-retention"))

        assert response.status_code == 200
        content = response.content.decode()
        assert reverse("admin:posthog_team_change", args=[self.team.id]) in content
        assert "Organization default" in content
        assert "September 2025" in content
