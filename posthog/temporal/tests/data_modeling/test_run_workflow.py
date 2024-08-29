import pytest

from posthog.temporal.data_modeling.run_workflow import ModelNode, RunModelActivityInputs, run_model_activity

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]


async def test_run_model_activity_activity(activity_environment, ateam):
    nodes_map = {
        "my_events_model": ModelNode(label="my_events_model", children={"my_joined_model"}, parents=set()),
        "my_persons_model": ModelNode(label="my_persons_model", children={"my_joined_model"}, parents=set()),
        "my_joined_model": ModelNode(
            label="my_joined_model", children=set(), parents={"my_events_model", "my_persons_model"}
        ),
    }
    run_model_activity_inputs = RunModelActivityInputs(team_id=ateam.pk, nodes_map=nodes_map)
    results = await activity_environment.run(run_model_activity, run_model_activity_inputs)

    assert results.completed == {"my_events_model", "my_persons_model", "my_joined_model"}
