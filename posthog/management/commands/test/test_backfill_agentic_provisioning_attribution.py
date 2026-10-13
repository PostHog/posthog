import csv
import uuid
import tempfile
from io import StringIO
from pathlib import Path

from posthog.test.base import BaseTest

from django.core.management import call_command

from parameterized import parameterized

from posthog.models.oauth import OAuthApplication
from posthog.models.team.team import Team
from posthog.models.team.team_provisioning_config import TeamProvisioningConfig

NO_ROW = "no_row"


class TestBackfillAgenticProvisioningAttribution(BaseTest):
    def setUp(self):
        super().setUp()
        self.apps = {
            "partner": self._create_app("partner", is_provisioning_partner=True),
            "other_partner": self._create_app("other-partner", is_provisioning_partner=True),
            "non_partner": self._create_app("non-partner", is_provisioning_partner=False),
        }

    def _create_app(self, client_id: str, *, is_provisioning_partner: bool) -> OAuthApplication:
        return OAuthApplication.objects.create(
            client_id=client_id,
            name=client_id,
            client_secret="",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://partner.example.com/callback",
            algorithm="RS256",
            is_provisioning_partner=is_provisioning_partner,
        )

    def _run_command(self, rows: list[tuple[object, object]], *args: str) -> str:
        out = StringIO()
        with tempfile.TemporaryDirectory() as tmp_dir:
            csv_path = Path(tmp_dir) / "attribution.csv"
            with csv_path.open("w", newline="") as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow(["team_id", "partner_id"])
                writer.writerows(rows)
            call_command("backfill_agentic_provisioning_attribution", str(csv_path), *args, stdout=out)
        return out.getvalue()

    def _seed_config(self, team: Team, application: str | None) -> None:
        TeamProvisioningConfig.objects.create(team=team, application=self.apps[application] if application else None)

    def _attribution(self, team: Team) -> str | None:
        config = TeamProvisioningConfig.objects.filter(team=team).first()
        if config is None:
            return NO_ROW
        if config.application_id is None:
            return None
        return next(name for name, app in self.apps.items() if app.id == config.application_id)

    @parameterized.expand(
        [
            ("creates_missing_row", NO_ROW, "partner", "partner"),
            ("fills_null_application", None, "partner", "partner"),
            ("never_replaces_another_application", "other_partner", "partner", "other_partner"),
            ("ignores_app_that_is_not_a_provisioning_partner", NO_ROW, "non_partner", NO_ROW),
        ]
    )
    def test_live_run_attribution(self, _name, existing, listed, expected):
        if existing != NO_ROW:
            self._seed_config(self.team, existing)

        self._run_command([(self.team.id, self.apps[listed].id)], "--live-run")

        assert self._attribution(self.team) == expected

    def test_dry_run_writes_nothing(self):
        null_team = Team.objects.create(organization=self.organization, name="Unclaimed team")
        self._seed_config(null_team, None)
        partner_id = self.apps["partner"].id

        output = self._run_command([(self.team.id, partner_id), (null_team.id, partner_id)])

        assert self._attribution(self.team) == NO_ROW
        assert self._attribution(null_team) is None
        assert "would create: 1" in output
        assert "would fill: 1" in output

    def test_live_run_skips_unresolvable_rows_and_attributes_the_rest(self):
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        conflicting_team = Team.objects.create(organization=self.organization, name="Conflicting team")
        partner_id = self.apps["partner"].id

        output = self._run_command(
            [
                (999_999_999, partner_id),
                (self.team.id, uuid.uuid4()),
                ("not-a-team-id", partner_id),
                (other_team.id, partner_id),
                (conflicting_team.id, partner_id),
                (conflicting_team.id, self.apps["other_partner"].id),
            ],
            "--live-run",
        )

        assert self._attribution(self.team) == NO_ROW
        assert self._attribution(other_team) == "partner"
        assert self._attribution(conflicting_team) == NO_ROW
        assert "skipped_team_not_found: 1" in output
        assert "skipped_application_not_found: 1" in output
        assert "skipped_invalid_row: 1" in output
        assert "skipped_conflicting_partners: 1" in output
