import pytest

from django.db.models.deletion import Collector

from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.models.team.util import _delete_llm_evaluations_for_teams, delete_team_records

from products.ai_observability.backend.models.evaluation_configs import EvaluationType, OutputType
from products.ai_observability.backend.models.evaluations import Evaluation
from products.ai_observability.backend.models.model_configuration import LLMModelConfiguration

pytestmark = [pytest.mark.django_db(transaction=True)]


def _bootstrap_team_with_evaluation() -> int:
    _, _, team = Organization.objects.bootstrap(None)
    config = LLMModelConfiguration.objects.create(team=team, provider="openai", model="gpt-4o")
    # bulk_create bypasses Evaluation.save() config validation — we only need a materializable row
    # whose model_configuration FK makes the Team cascade take the SET_NULL path.
    Evaluation.objects.bulk_create(
        [
            Evaluation(
                team=team,
                model_configuration=config,
                name="deep",
                evaluation_type=EvaluationType.LLM_JUDGE,
                output_type=OutputType.BOOLEAN,
            )
        ]
    )
    return team.id


# NOTE: test_evaluation_recurses_when_loaded_deferred and test_team_cascade_recurses_without_predelete
# are regression diagnostics for an upstream Evaluation model bug (deferred load of enabled/status
# recurses). When the AI observability team fixes that model bug, these two tests will start failing
# because the RecursionError they assert on will no longer be raised — remove or update them then.
# The pre-delete behaviour itself is covered by test_predelete_evaluations_unblocks_team_deletion.


def test_evaluation_recurses_when_loaded_deferred():
    """Documents the upstream model bug the pre-delete works around."""
    team_id = _bootstrap_team_with_evaluation()
    evaluation_id = Evaluation.objects.filter(team_id=team_id).values_list("id", flat=True).first()
    assert evaluation_id is not None
    with pytest.raises(RecursionError):
        # from_db reads enabled/status to snapshot a baseline; with them deferred, that read
        # re-fetches the row and re-enters from_db forever.
        Evaluation.objects.only("id").get(id=evaluation_id)


def test_team_cascade_recurses_without_predelete():
    # Mirrors the production diagnostic: collecting the Team cascade materializes the evaluation
    # via SET_NULL on model_configuration and overflows. collect() gathers only; nothing is deleted.
    team_id = _bootstrap_team_with_evaluation()
    with pytest.raises(RecursionError):
        Collector(using="default").collect(list(Team.objects.filter(id=team_id)))


def test_predelete_evaluations_unblocks_team_deletion():
    team_id = _bootstrap_team_with_evaluation()

    _delete_llm_evaluations_for_teams([team_id])
    delete_team_records([team_id])

    assert not Team.objects.filter(id=team_id).exists()
