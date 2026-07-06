from io import StringIO

from posthog.test.base import BaseTest

from django.core.management import call_command

from parameterized import parameterized

from posthog.models import Team


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
        # Pin the team IDs the command samples on. Relying on auto-increment IDs makes this flaky:
        # the sampling hash clumps across consecutive IDs and the starting ID drifts between CI runs
        # (the DB is reused), so a run of 100 IDs is almost always nearly-all or nearly-none sampled.
        # These IDs are spread across the hash space so exactly half fall under a 0.5 rate; the golden
        # values below are precomputed offline from the sampling hash, not re-derived from it at runtime.
        base, step = 10_000_000, 100_003
        team_ids = [base + i * step for i in range(100)]
        for team_id in team_ids:
            Team.objects.create(id=team_id, organization=self.organization, name=f"Team {team_id}")

        call_command(
            "set_recorder_script",
            "--script=test-recorder",
            "--sample-rate=0.5",
        )

        updated_ids = set(
            Team.objects.filter(id__in=team_ids, extra_settings__has_key="recorder_script").values_list(
                "id", flat=True
            )
        )

        assert len(updated_ids) == 50
        assert 10_700_021 in updated_ids  # hashes below the 0.5 threshold
        assert 10_100_003 not in updated_ids  # hashes above the 0.5 threshold

    def test_bulk_updates_in_batches(self):
        # Use bulk_create with a shared project to avoid 2500 individual
        # Team.objects.create() calls (each of which also creates a Project
        # in its own transaction). The test only cares that 2500 teams exist
        # for the management command to iterate over.
        Team.objects.bulk_create(
            [Team(organization=self.organization, project=self.project, name=f"Team {i}") for i in range(2500)]
        )

        out = StringIO()
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
