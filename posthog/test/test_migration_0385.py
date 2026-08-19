import pytest
from posthog.test.base import NonAtomicTestMigrations

pytestmark = pytest.mark.skip("old migrations slow overall test run down")


class FixingExceptionAutocaptureMigration(NonAtomicTestMigrations):
    migrate_from = "0384_activity_log_was_impersonated"
    migrate_to = "0385_exception_autocapture_off_for_all"

    CLASS_DATA_LEVEL_SETUP = False

    def setUpBeforeMigration(self, apps):
        Organization = apps.get_model("posthog", "Organization")
        org = Organization.objects.create(name="o1")

        Team = apps.get_model("posthog", "Team")

        # there are three states... create a Team for each
        team_null = Team.objects.create(name="t1", organization=org)
        team_null.autocapture_exceptions_opt_in = None
        team_null.save()

        team_true = Team.objects.create(name="t2", organization=org)
        team_true.autocapture_exceptions_opt_in = True
        team_true.save()

        team_false = Team.objects.create(name="t3", organization=org)
        team_false.autocapture_exceptions_opt_in = False
        team_false.save()

    def test_migrate_to_create_session_recordings(self):
        apps = self.apps
        if apps is None:
            # obey mypy
            raise Exception("apps is None")

        Team = apps.get_model("posthog", "Team")

        assert list(Team.objects.all().values_list("name", "autocapture_exceptions_opt_in").order_by("name")) == [
            # unchanged
            ("t1", None),
            # set to False
            ("t2", False),
            # Unchanged
            ("t3", False),
        ]

    def tearDown(self):
        apps = self.apps
        if apps is None:
            # obey mypy
            raise Exception("apps is None")

        Organization = apps.get_model("posthog", "Organization")
        Team = apps.get_model("posthog", "Team")

        Team.objects.all().delete()
        Organization.objects.all().delete()
