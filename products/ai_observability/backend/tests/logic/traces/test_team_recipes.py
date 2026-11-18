import itertools

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext

from posthog.models import Organization, Team

from products.ai_observability.backend.logic.message_normalizer import run_limits as run_limits_module
from products.ai_observability.backend.logic.message_normalizer.normalizer import compile_candidate_recipe
from products.ai_observability.backend.logic.message_normalizer.run_limits import time_limit
from products.ai_observability.backend.logic.message_normalizer.values import Value
from products.ai_observability.backend.logic.traces.team_recipes import team_normalizer, team_normalizer_with
from products.ai_observability.backend.models.parser_recipe import ParserRecipe

TICKET_RECIPE = """
rules:
  - on:
      ticket_id: { exists: true }
      summary: { is: string }
    emit:
      role: system
      content: 'Ticket $.ticket_id: $.summary'
"""
NOT_A_RECIPE = "rules: [this is: not valid"
TICKET = {"ticket_id": "T-42", "summary": "Refund requested"}
CONVERSATION = [{"role": "user", "content": "Hi"}]


class TestTeamNormalizer(BaseTest):
    def _contents(self, team_id: int, value: Value) -> list[object]:
        outcome = team_normalizer(team_id).normalize_messages(value, "user")
        return [message["content"] for message in outcome.messages]

    def test_team_recipe_normalizes_a_shape_the_builtins_do_not_recognize(self):
        ParserRecipe.objects.unscoped().create(team=self.team, name="tickets", source=TICKET_RECIPE)

        assert self._contents(self.team.id, TICKET) == ["Ticket T-42: Refund requested"]
        assert team_normalizer(self.team.id).normalize_messages(TICKET, "user").recognized

    def test_without_the_recipe_the_shape_is_not_recognized(self):
        assert not team_normalizer(self.team.id).normalize_messages(TICKET, "user").recognized

    def test_recipe_that_does_not_compile_is_skipped_and_builtins_still_work(self):
        ParserRecipe.objects.unscoped().create(team=self.team, name="broken", source=NOT_A_RECIPE)
        ParserRecipe.objects.unscoped().create(team=self.team, name="tickets", source=TICKET_RECIPE)

        assert self._contents(self.team.id, CONVERSATION) == ["Hi"]
        assert self._contents(self.team.id, TICKET) == ["Ticket T-42: Refund requested"]

    def test_another_teams_recipe_does_not_apply(self):
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other"), name="Other")
        ParserRecipe.objects.unscoped().create(team=other_team, name="tickets", source=TICKET_RECIPE)

        assert not team_normalizer(self.team.id).normalize_messages(TICKET, "user").recognized

    def test_an_edited_recipe_applies_its_new_source(self):
        recipe = ParserRecipe.objects.unscoped().create(team=self.team, name="tickets", source=TICKET_RECIPE)
        assert self._contents(self.team.id, TICKET) == ["Ticket T-42: Refund requested"]

        recipe.source = TICKET_RECIPE.replace("Ticket", "Case")
        recipe.save()

        assert self._contents(self.team.id, TICKET) == ["Case T-42: Refund requested"]

    def test_a_cached_recipe_does_not_read_its_source_again(self):
        ParserRecipe.objects.unscoped().create(team=self.team, name="tickets", source=TICKET_RECIPE)
        team_normalizer(self.team.id)

        with CaptureQueriesContext(connection) as queries:
            assert self._contents(self.team.id, TICKET) == ["Ticket T-42: Refund requested"]

        assert not any('"source"' in query["sql"] for query in queries.captured_queries)

    def test_a_recipe_reached_after_the_deadline_is_skipped_for_that_read_only(self):
        ParserRecipe.objects.unscoped().create(team=self.team, name="tickets", source=TICKET_RECIPE)

        with time_limit(0):
            past_deadline = team_normalizer(self.team.id)

        assert not past_deadline.normalize_messages(TICKET, "user").recognized
        assert self._contents(self.team.id, TICKET) == ["Ticket T-42: Refund requested"]

    def test_a_recipe_whose_compile_overruns_the_deadline_is_skipped_for_that_read_only(self):
        ParserRecipe.objects.unscoped().create(team=self.team, name="tickets", source=TICKET_RECIPE)
        # The deadline is set at 0 and expires at 1, the check before the parse reads 0.5, and every later check reads
        # 2, so the read runs out of time inside the compile.
        clock = itertools.chain([0.0, 0.5], itertools.repeat(2.0))

        with patch.object(run_limits_module, "time") as fake_time:
            fake_time.monotonic.side_effect = clock
            with time_limit(1):
                overran = team_normalizer(self.team.id)

        assert not overran.normalize_messages(TICKET, "user").recognized
        assert self._contents(self.team.id, TICKET) == ["Ticket T-42: Refund requested"]

    def test_a_candidate_runs_after_the_teams_saved_recipes(self):
        candidate = compile_candidate_recipe(TICKET_RECIPE.replace("Ticket", "Candidate"))

        alone = team_normalizer_with(self.team.id, candidate).normalize_messages(TICKET, "user")
        ParserRecipe.objects.unscoped().create(team=self.team, name="tickets", source=TICKET_RECIPE)
        behind_saved = team_normalizer_with(self.team.id, candidate).normalize_messages(TICKET, "user")

        assert [message["content"] for message in alone.messages] == ["Candidate T-42: Refund requested"]
        assert [message["content"] for message in behind_saved.messages] == ["Ticket T-42: Refund requested"]
