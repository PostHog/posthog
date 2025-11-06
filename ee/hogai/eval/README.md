# AI evals

We use AI evaluations (evals) to test our AI outputs against a curated set of inputs. Evals allow us to verify prompt performance, spot regressions, or compare different model versions.

![Greg Brockman on evals](https://res.cloudinary.com/dwxrm0iul/image/upload/v1731538464/tweet-1733553161884127435_2_cpectu.png)

We currently use [Braintrust](https://braintrust.dev) as our evaluation platform. Braintrust tracks evaluation results, including LLM traces - which helps both track performance, and dig into any issues on a case-by-case basis. To access Braintrust and/or get an API key for it, ask #team-posthog-ai.

## CI evals

1. Export environment variable `BRAINTRUST_API_KEY` (ask #team-posthog-ai).
2. Run all evals with:

   ```bash
   pytest ee/hogai/eval/ci
   ```

   The key bit is specifying the `ee/hogai/eval/ci` directory – that activates our eval-specific config, `ee/hogai/eval/pytest.ini`!

   As always with pytest, you can also run a specific file, e.g. `pytest ee/hogai/eval/ci/eval_root.py`. Apply the `--eval sql` argument to only run evals for test cases that contain `sql`.

3. Voila! Max ran, evals executed, and results and traces uploaded to the Braintrust platform + summarized in the terminal.

For historical eval runs, see the [full Experiments list in Braintrust](https://www.braintrust.dev/app/PostHog/p/Max%20AI/experiments).

## Offline evals

### Datasets

For offline evaluation, you typically need to collect a dataset first. You can do that in [PostHog LLM Analytics](https://us.posthog.com/llm-analytics/datasets). There are a few requirements for the shape of a dataset item:

- The `input`, `output`, `metadata` fields must be valid JSON objects.
- The `metadata` must contain the `team_id` field.

Remember to continuously review traces and curate your datasets–it's the key to quality.

### Evaluation module

Additionally, you need an evaluation module in `ee/hogai/eval/offline/*` that contains an evaluation test case with defined scorers. The test suite may contain multiple test cases, and they are separately reported. For example, if we wanted to evaluate SQL, we could implement the following evaluation module:

```python
import pytest

from braintrust import EvalCase, Score
from pydantic import BaseModel

from posthog.schema import HumanMessage

from posthog.models import Team

from ee.hogai.eval.base import MaxPrivateEval
from ee.hogai.eval.offline.conftest import EvaluationContext, capture_score, get_eval_context
from ee.hogai.eval.schema import DatasetInput
from ee.hogai.eval.scorers.sql import SQLSemanticsCorrectness, SQLSyntaxCorrectness
from ee.hogai.graph.graph import AssistantGraph
from ee.hogai.utils.types import AssistantState
from ee.models import Conversation


class EvalOutput(BaseModel):
    ...

async def call_graph(entry: DatasetInput, *args):
    eval_ctx = get_eval_context() # Get local evaluation context
    team = await Team.objects.aget(id=entry.team_id)
    conversation = await Conversation.objects.acreate(team=team, user=eval_ctx.user)
    graph = AssistantGraph(team, eval_ctx.user).compile_full_graph()
    state = await graph.ainvoke(
        AssistantState(messages=[HumanMessage(content=entry.input["query"])]),
        {
            "callbacks": eval_ctx.get_callback_handlers(entry.trace_id),
            "configurable": {
                "thread_id": conversation.id,
                "team": team,
                "user": eval_ctx.user,
                "distinct_id": eval_ctx.distinct_id,
            },
        },
    )
    return EvalOutput(...)


@capture_score # Decorator to automatically capture the score result
async def sql_semantics_scorer(input: DatasetInput, expected: str, output: EvalOutput, **kwargs) -> Score:
    # Make sure you pass the traced OpenAI client to a scorer, so the scorer traces are captured.
    client = get_eval_context().get_openai_client_for_tracing(input.trace_id)
    metric = SQLSemanticsCorrectness(client=client)
    return await metric.eval_async(...)


@capture_score # Decorator to automatically capture the score result
async def sql_syntax_scorer(input: DatasetInput, expected: str, output: EvalOutput, **kwargs) -> Score:
    # Algorithmic scorer doesn't need the traced OpenAI client.
    metric = SQLSyntaxCorrectness()
    return await metric.eval_async(...)


# Generate eval cases from dataset items
def generate_test_cases(eval_ctx: EvaluationContext):
    for entry in eval_ctx.dataset_inputs:
        yield EvalCase(input=entry, expected=entry.expected["output"])


@pytest.mark.django_db
async def eval_offline_sql(eval_ctx: EvaluationContext, pytestconfig):
    await MaxPrivateEval(
        experiment_name=eval_ctx.formatted_experiment_name,
        task=call_graph,
        scores=[sql_syntax_scorer, sql_semantics_scorer],
        data=generate_test_cases(eval_ctx),
        pytestconfig=pytestconfig,
    )
```

### Running an evaluation

Log in to [Dagster Cloud](https://posthog.dagster.cloud/locations/dags.locations.max_ai/jobs/run_evaluation/playground) and run a new `run_evaluation` job with a following config:

```yaml
ops:
  prepare_dataset:
    config:
      dataset_id: '01992de8-3773-7946-afad-e028d45eba01' # Dataset ID
  spawn_evaluation_container:
    config:
      evaluation_module: ee/hogai/eval/offline/eval_sql.py # Evaluation module
      image_name: posthog-ai-evals # Leave as is or provide another image
      image_tag: master # Use master or commit hash of the branch you want to evaluate
```

The job will pull the provided dataset, validate dataset items, export team data, run the evaluation, and report results back to you.

If you want to run an evaluation for a branch that is not `master`, you will need to build an image with the `build-ai-evals-image` tag. Once the CI is complete, you are ready to run the evaluation.

### Viewing evaluation results

Evaluation results are automatically reported to the `#evals-max-ai` channel in Slack. You can also access the same data in the Dagster asset catalog. The report will contain links with captured traces for the evaluation run.
