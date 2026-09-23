from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError

from parameterized import parameterized

from posthog.models.organization import Organization
from posthog.models.scoping import team_scope
from posthog.models.user import User

from products.autoresearch.backend.models import AutoresearchPipeline

COMMAND = "products.autoresearch.backend.management.commands.autoresearch_train"


class TestAutoresearchTrainCommand(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        with team_scope(self.team.id):
            self.pipeline = AutoresearchPipeline.objects.create(
                team=self.team, created_by=self.user, name="p", target_event="$pageview", horizon_days=7
            )

    @parameterized.expand(
        [
            ("user_outside_the_team", {"outsider": True}),
            ("archived_pipeline", {"status": AutoresearchPipeline.Status.ARCHIVED}),
            ("zero_iterations", {"iterations": 0}),
            ("flag_off", {"flag": False}),
        ]
    )
    def test_real_training_is_refused_before_launch(self, _name, case) -> None:
        user_id = self.user.pk
        if case.get("outsider"):
            outsider = User.objects.create_user(email="outsider@example.com", password="x", first_name="Out")
            Organization.objects.create(name="Elsewhere").members.add(outsider)
            user_id = outsider.pk
        if "status" in case:
            with team_scope(self.team.id):
                self.pipeline.status = case["status"]
                self.pipeline.save()

        with (
            patch(f"{COMMAND}.has_autoresearch_access", return_value=case.get("flag", True)),
            patch(f"{COMMAND}.run_training") as run_training,
            self.assertRaises(CommandError),
        ):
            call_command(
                "autoresearch_train",
                pipeline_id=str(self.pipeline.pk),
                user_id=user_id,
                iterations=case.get("iterations", 5),
            )
        run_training.assert_not_called()
