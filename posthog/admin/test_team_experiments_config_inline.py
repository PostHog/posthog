from posthog.test.base import BaseTest

from django.forms import ModelForm, modelform_factory

from posthog.admin.inlines.team_experiments_config_inline import TeamExperimentsConfigInlineForm
from posthog.models.team.extensions import get_or_create_team_extension

from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig


class TestTeamExperimentsConfigInlineForm(BaseTest):
    def _form(self, data: dict) -> ModelForm:
        # The admin builds the concrete form from the inline's fieldsets; mirror that here.
        form_class = modelform_factory(
            TeamExperimentsConfig,
            form=TeamExperimentsConfigInlineForm,
            fields=["experiment_recalculation_times"],
        )
        config = get_or_create_team_extension(self.team, TeamExperimentsConfig)
        return form_class(data=data, instance=config)

    def test_rejects_recalculation_times_the_api_would_reject(self):
        form = self._form({"experiment_recalculation_times": '["08:00:00", "09:00:00"]'})
        self.assertFalse(form.is_valid())
        self.assertIn("experiment_recalculation_times", form.errors)

    def test_admin_saves_recalculation_times(self):
        form = self._form({"experiment_recalculation_times": '["14:00:00", "02:00:00"]'})
        self.assertTrue(form.is_valid(), form.errors)
        config = form.save()
        self.assertEqual(config.experiment_recalculation_times, ["14:00:00", "02:00:00"])
