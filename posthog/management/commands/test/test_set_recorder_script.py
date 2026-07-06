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

    def test_samples_the_expected_teams_at_rate_0_5(self):
        # Fixed ids are required: sample_on_property now hashes into 10000 buckets (was 100 before
        # #68598 raised the resolution so sub-1% rates stop truncating to zero). At that finer
        # resolution a block of consecutive auto-increment ids lands almost all-or-nothing mod 10000,
        # so the old "roughly 50 of 100 sampled" assertion flipped to 0 or 100 depending on the id
        # block CI happened to assign. These fixed ids give a stable split, and the expected set below
        # is derived independently of the command's sampling code: for these 100 ids
        # simple_hash(id) % 10000 lands under 5000 for ids 9_400_000..9_400_079 and at/above it for
        # the last 20. Asserting against this precomputed 80/20 split (rather than re-deriving it with
        # sample_on_property) proves the command samples correctly, not merely that it matches itself.
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

        expected_ids = set(range(9_400_000, 9_400_080))
        updated_ids = set(Team.objects.filter(extra_settings__has_key="recorder_script").values_list("id", flat=True))

        assert updated_ids == expected_ids

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
