from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError

from posthog.models.organization import Organization
from posthog.models.user import User

from products.autoresearch.backend.dataset.validation import ValidationResult


class TestAutoresearchValidateCommand(BaseTest):
    def test_user_without_team_access_is_refused_before_any_query(self) -> None:
        outsider = User.objects.create_user(email="outsider@example.com", password="x", first_name="Out")
        Organization.objects.create(name="Elsewhere").members.add(outsider)
        with (
            patch(
                "products.autoresearch.backend.management.commands.autoresearch_validate.validate_pipeline_definition"
            ) as validate,
            self.assertRaises(CommandError),
        ):
            call_command("autoresearch_validate", team_id=self.team.pk, target="$pageview", user_id=outsider.pk)
        validate.assert_not_called()

    def test_member_is_passed_to_validation(self) -> None:
        ok = ValidationResult(
            can_proceed=True,
            requires_acknowledgement=False,
            estimated_training_rows=1000,
            positive_count=100,
            negative_count=900,
            base_rate=0.1,
            inference_population_size=1000,
        )
        with patch(
            "products.autoresearch.backend.management.commands.autoresearch_validate.validate_pipeline_definition",
            return_value=ok,
        ) as validate:
            call_command("autoresearch_validate", team_id=self.team.pk, target="$pageview", user_id=self.user.pk)
        assert validate.call_args.kwargs["user"] == self.user
