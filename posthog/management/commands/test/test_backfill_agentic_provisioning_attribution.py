import csv
import uuid
import tempfile
from datetime import timedelta
from io import StringIO
from pathlib import Path

from posthog.test.base import BaseTest

from django.core.management import call_command

from parameterized import parameterized

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.oauth import OAuthApplication
from posthog.models.organization import Organization
from posthog.models.organization_integration import OrganizationIntegration
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

    def _run_command(self, rows: list[tuple[object, object]], *args: str) -> dict[str, str]:
        out = StringIO()
        with tempfile.TemporaryDirectory() as tmp_dir:
            csv_path = Path(tmp_dir) / "attribution.csv"
            with csv_path.open("w", newline="") as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow(["team_id", "partner_id"])
                writer.writerows(rows)
            call_command("backfill_agentic_provisioning_attribution", str(csv_path), *args, stdout=out)
        return dict(line.rsplit(": ", 1) for line in out.getvalue().splitlines() if ": " in line)

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
        assert self._recorded_creator() is None
        assert output["would create"] == "1"
        assert output["would fill"] == "1"
        assert output["provisioning_api organizations, would create"] == "1"
        assert not ActivityLog.objects.filter(
            organization_id=self.organization.id, scope="Organization", activity="updated"
        ).exists()

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
        assert output["skipped_team_not_found"] == "1"
        assert output["skipped_application_not_found"] == "1"
        assert output["skipped_invalid_row"] == "1"
        assert output["skipped_conflicting_partners"] == "1"

    def _recorded_creator(self) -> tuple[str, str | None] | None:
        self.organization.refresh_from_db()
        if self.organization.provisioning_source is None:
            return None
        application = next(
            (name for name, app in self.apps.items() if app.id == self.organization.provisioning_application_id), None
        )
        return self.organization.provisioning_source, application

    def _add_vercel_installation(self, config: dict[str, object]) -> None:
        OrganizationIntegration.objects.create(
            organization=self.organization,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            integration_id="icfg_backfill_test",
            config=config,
        )

    @parameterized.expand(
        [
            ("csv_partner_on_first_team", "csv", "first_team", ("provisioning_api", "partner")),
            ("csv_partner_on_later_team", "csv", "later_team", None),
            ("csv_partner_on_lowest_team_created_after_organization", "csv", "lowest_team_created_later", None),
            ("csv_partner_on_first_team_attributed_to_other_partner", "csv", "first_team_other_partner", None),
            ("unmarked_vercel_install", "vercel_marketplace", None, None),
            ("vercel_connectable_link", "vercel_connectable", None, None),
            (
                "csv_and_unmarked_vercel_install",
                "csv+vercel_marketplace",
                "first_team",
                ("provisioning_api", "partner"),
            ),
        ]
    )
    def test_live_run_records_organization_creator(
        self, _name: str, sources: str, team_choice: str | None, expected: tuple[str, str | None] | None
    ) -> None:
        later_team = Team.objects.create(organization=self.organization, name="Later team")
        team = later_team if team_choice == "later_team" else self.team
        if team_choice == "lowest_team_created_later":
            Team.objects.filter(id=self.team.id).update(created_at=self.organization.created_at + timedelta(days=30))
        if team_choice == "first_team_other_partner":
            self._seed_config(self.team, "other_partner")
        rows: list[tuple[object, object]] = []
        if "csv" in sources:
            rows.append((team.id, self.apps["partner"].id))
        if "vercel_marketplace" in sources:
            self._add_vercel_installation({"scopes": ["read-write:integration-configuration"]})
        if "vercel_connectable" in sources:
            self._add_vercel_installation({"type": "connectable"})

        self._run_command(rows, "--live-run")

        assert self._recorded_creator() == expected
        logs = ActivityLog.objects.filter(
            organization_id=self.organization.id, scope="Organization", activity="updated"
        )
        assert logs.count() == int(expected is not None)
        if expected is not None:
            detail = logs.get().detail
            assert detail is not None
            assert detail["trigger"]["job_id"] == "backfill_agentic_provisioning_attribution"
            assert all(change["action"] == "created" for change in detail["changes"])
            assert {change["field"]: change["after"] for change in detail["changes"]} == {
                "provisioning_source": expected[0],
                "provisioning_application": {
                    "id": str(self.apps["partner"].id),
                    "name": self.apps["partner"].name,
                },
            }

    def test_live_run_never_replaces_recorded_organization_creator(self):
        Organization.objects.filter(id=self.organization.id).update(
            provisioning_source=Organization.ProvisioningSource.PROVISIONING_API,
            provisioning_application=self.apps["other_partner"],
        )

        output = self._run_command([(self.team.id, self.apps["partner"].id)], "--live-run")

        assert self._recorded_creator() == ("provisioning_api", "other_partner")
        assert output["provisioning_api organizations, skipped_other_partner"] == "1"
        assert not ActivityLog.objects.filter(
            organization_id=self.organization.id, scope="Organization", activity="updated"
        ).exists()
