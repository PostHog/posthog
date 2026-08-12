from io import StringIO

from posthog.test.base import BaseTest
from unittest import mock

from django.core.management import call_command

from parameterized import parameterized

from posthog.models import Team
from posthog.sampling import sample_on_property


class TestSetRecorderScriptCommand(BaseTest):
    def test_dry_run_mode(self):
        team1 = Team.objects.create(organization=self.organization, name="Team 1")
        team2 = Team.objects.create(organization=self.organization, name="Team 2")

        out = StringIO()
        call_command(
            "set_recorder_script",
            "--script=test-recorder",
            "--sample-rate=1.0",
            "--dry-run",
            stdout=out,
        )

        output = out.getvalue()
        assert "DRY RUN MODE" in output
        assert "Would update" in output

        team1.refresh_from_db()
        team2.refresh_from_db()
        assert team1.extra_settings is None
        assert team2.extra_settings is None

    def test_sets_recorder_script_for_all_teams(self):
        team1 = Team.objects.create(organization=self.organization, name="Team 1")
        team2 = Team.objects.create(organization=self.organization, name="Team 2")

        out = StringIO()
        call_command(
            "set_recorder_script",
            "--script=test-recorder",
            "--sample-rate=1.0",
            stdout=out,
        )

        output = out.getvalue()
        assert "Successfully updated" in output

        team1.refresh_from_db()
        team2.refresh_from_db()
        assert team1.extra_settings == {"recorder_script": "test-recorder"}
        assert team2.extra_settings == {"recorder_script": "test-recorder"}

    def test_skips_teams_with_existing_recorder_script(self):
        self.team.extra_settings = {"recorder_script": "existing"}
        self.team.save()

        team_without = Team.objects.create(organization=self.organization, name="Team without")

        out = StringIO()
        call_command(
            "set_recorder_script",
            "--script=new-recorder",
            "--sample-rate=1.0",
            stdout=out,
        )

        output = out.getvalue()
        assert "Found 1 teams without recorder_script set" in output

        self.team.refresh_from_db()
        team_without.refresh_from_db()
        assert self.team.extra_settings == {"recorder_script": "existing"}
        assert team_without.extra_settings == {"recorder_script": "new-recorder"}

    def test_preserves_other_extra_settings_fields(self):
        team = Team.objects.create(organization=self.organization, name="Team", extra_settings={"other_field": "value"})

        call_command(
            "set_recorder_script",
            "--script=test-recorder",
            "--sample-rate=1.0",
        )

        team.refresh_from_db()
        assert team.extra_settings == {"other_field": "value", "recorder_script": "test-recorder"}

    @parameterized.expand(
        [
            ("invalid_low", -0.1),
            ("invalid_high", 1.1),
        ]
    )
    def test_validates_sample_rate(self, _name, sample_rate):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError) as cm:
            call_command(
                "set_recorder_script",
                f"--script=test-recorder",
                f"--sample-rate={sample_rate}",
            )

        assert "Sample rate must be between 0.0 and 1.0" in str(cm.exception)

    def test_sampling_is_consistent(self):
        # simple_hash maps consecutive decimal ids into a narrow band mod 10000, so a sequence-assigned
        # id block usually samples all-or-nothing; fixed ids give a deterministic 80/20 split at rate 0.5.
        Team.objects.bulk_create(
            [
                Team(id=9_400_000 + i, organization=self.organization, project=self.project, name=f"Team {i}")
                for i in range(100)
            ]
        )

        call_command(
            "set_recorder_script",
            "--script=test-recorder",
            "--sample-rate=0.5",
        )

        all_ids = set(Team.objects.values_list("id", flat=True))
        expected_ids = {team_id for team_id in all_ids if sample_on_property(str(team_id), 0.5)}
        updated_ids = set(Team.objects.filter(extra_settings__has_key="recorder_script").values_list("id", flat=True))

        assert updated_ids == expected_ids
        # Both sides non-empty proves the command actually filtered rather than updating none or all.
        assert updated_ids and all_ids - updated_ids

    def test_bulk_updates_in_batches(self):
        # Use bulk_create with a shared project to avoid 2500 individual
        # Team.objects.create() calls (each of which also creates a Project
        # in its own transaction). The test only cares that 2500 teams exist
        # for the management command to iterate over.
        Team.objects.bulk_create(
            [Team(organization=self.organization, project=self.project, name=f"Team {i}") for i in range(2500)]
        )

        out = StringIO()
        # team.save() fans out to unrelated post_save receivers that each do per-team work:
        # the team-token cache write runs a full DRF serialization plus a cache write, and
        # hog function / hog flow refresh each run their own DB query. Irrelevant to this
        # command's batching behaviour, just 2500x avoidable overhead each — mock them out
        # like any other unrelated side effect that isn't under test. With these mocked,
        # each save is a single UPDATE, which is this test's floor.
        with (
            mock.patch("products.cdp.backend.tasks.hog_functions.refresh_affected_hog_functions.delay"),
            mock.patch("products.workflows.backend.tasks.hog_flows.refresh_affected_hog_flows.delay"),
            mock.patch("posthog.models.team.team.set_team_in_cache"),
        ):
            call_command(
                "set_recorder_script",
                "--script=test-recorder",
                "--sample-rate=1.0",
                stdout=out,
            )

        output = out.getvalue()
        assert "Updated 1000 teams so far..." in output
        assert "Updated 2000 teams so far..." in output

        updated_teams = Team.objects.filter(extra_settings__has_key="recorder_script").count()
        assert updated_teams > 2400
