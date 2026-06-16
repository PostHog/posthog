# Sentiment evaluation type plan

## Scope

Add sentiment analysis as a third AI observability evaluation type, alongside `llm_judge` and `hog`.

This plan covers only the evaluation config, scheduler, manual run, Temporal workflow, emitted `$ai_evaluation` event shape, metrics, and tests.
Reading sentiment from evaluation events and deprecating the current on-read sentiment API are explicitly out of scope for this first implementation.

Sentiment evaluations should not participate in the existing pass/fail evaluation reporting flow in the first pass.
Do not auto-create report configs for sentiment evaluations, and do not show evaluation report configuration UI while creating or editing a sentiment evaluation.

## Current state

Evaluation configs are limited to two runtimes:

- `llm_judge`
- `hog`

`products/ai_observability/backend/models/evaluation_configs.py` defines both `EvaluationType` and `OutputType`.
`OutputType` is currently only `boolean`, and the existing evaluation stack assumes pass/fail/N/A results in several places.

The `run-evaluation` Temporal workflow lives in `posthog/temporal/ai_observability/run_evaluation.py`.
It currently branches on `evaluation_type == "hog"` and treats every other value as an LLM judge.
That means a new `sentiment` type would currently fall into the LLM judge path and fail.

Sentiment analysis already exists outside evaluations:

- API entry point: `products/ai_observability/backend/api/sentiment.py`
- Temporal activity: `posthog/temporal/ai_observability/sentiment/activities.py`
- Extraction helpers: `posthog/temporal/ai_observability/sentiment/extraction.py`
- Result aggregation helpers: `posthog/temporal/ai_observability/sentiment/utils.py`
- ONNX model wrapper: `posthog/temporal/ai_observability/sentiment/model.py`

The new evaluation runtime should reuse those sentiment extraction/model helpers, but it should emit results as `$ai_evaluation` events instead of returning synchronously to the on-read API.

## Recommended contract

Add `sentiment` as a first-class evaluation runtime.

Add a new output type instead of forcing sentiment into `boolean`:

```python
class EvaluationType(models.TextChoices):
    LLM_JUDGE = "llm_judge", "LLM as a judge"
    HOG = "hog", "Hog"
    SENTIMENT = "sentiment", "Sentiment analysis"

class OutputType(models.TextChoices):
    BOOLEAN = "boolean", "Boolean (Pass/Fail)"
    SENTIMENT = "sentiment", "Sentiment"
```

Use a small/defaulted config shape:

```python
class SentimentEvalConfig(BaseModel):
    source: Literal["user_messages"] = "user_messages"

class SentimentOutputConfig(BaseModel):
    pass
```

Register this pairing:

```python
(EvaluationType.SENTIMENT.value, OutputType.SENTIMENT.value): (SentimentEvalConfig, SentimentOutputConfig)
```

Do not emit `$ai_evaluation_result` for sentiment in the first pass.
That property is currently interpreted as pass/fail by summaries, reports, runs tables, metrics, and clustering.
Sentiment should use sentiment-specific properties until the read paths are made output-type aware.

Because sentiment does not emit a pass/fail result, it must also be excluded from the current evaluation report flow.
The current report metrics are pass-rate based and would be misleading for sentiment events.

## Emitted event shape

Keep the shared `$ai_evaluation` linkage properties:

- `$ai_evaluation_id`
- `$ai_evaluation_name`
- `$ai_evaluation_type = "online"`
- `$ai_evaluation_runtime = "sentiment"`
- `$ai_evaluation_start_time`
- `$ai_evaluation_reasoning`
- `$ai_target_event_id`
- `$ai_target_event_type`
- `$ai_target_id`
- `$ai_target_type = "generation_uuid"`
- `$ai_trace_id`
- `$session_id`

Add sentiment-specific properties:

- `$ai_sentiment_label`
- `$ai_sentiment_score`
- `$ai_sentiment_scores`
- `$ai_sentiment_messages`
- `$ai_sentiment_message_count`

Example payload:

```json
{
  "$ai_evaluation_runtime": "sentiment",
  "$ai_evaluation_reasoning": "User sentiment classified as negative.",
  "$ai_sentiment_label": "negative",
  "$ai_sentiment_score": 0.82,
  "$ai_sentiment_scores": {
    "positive": 0.05,
    "neutral": 0.13,
    "negative": 0.82
  },
  "$ai_sentiment_messages": {
    "0": {
      "label": "negative",
      "score": 0.91,
      "scores": {
        "positive": 0.02,
        "neutral": 0.07,
        "negative": 0.91
      }
    }
  },
  "$ai_sentiment_message_count": 1
}
```

Do not emit LLM cost/model fields for sentiment:

- `$ai_model`
- `$ai_provider`
- `$ai_input_tokens`
- `$ai_output_tokens`
- `$ai_evaluation_model`
- `$ai_evaluation_provider`
- `$ai_evaluation_key_type`
- `$ai_evaluation_key_id`

## Implementation steps

### 1. Add model/config support

Files:

- `products/ai_observability/backend/models/evaluation_configs.py`
- `products/ai_observability/backend/models/evaluations.py`

Changes:

- Add `EvaluationType.SENTIMENT`.
- Add `OutputType.SENTIMENT`.
- Add Pydantic config/output models.
- Register `(sentiment, sentiment)` in `EVALUATION_CONFIG_MODELS`.
- Generate a Django migration for the updated `choices`.
- Keep Hog bytecode compilation limited to `EvaluationType.HOG`.

### 2. Update evaluation API validation

File:

- `products/ai_observability/backend/api/evaluations.py`

Changes:

- Update serializer help text for `evaluation_type`, `evaluation_config`, and `output_type`.
- Treat sentiment like Hog for re-enable provider/trial gates.
- Do not require `model_configuration` for sentiment.
- Update config-length tracking so sentiment does not fall through to the LLM prompt logic.
- Skip default evaluation report creation for sentiment, because reports are currently pass/fail oriented.

### 3. Hide report configuration for sentiment evals

Files:

- `products/ai_observability/frontend/evaluations/AIObservabilityEvaluation.tsx`
- `products/ai_observability/frontend/evaluations/llmEvaluationLogic.ts`
- `products/ai_observability/frontend/evaluations/components/EvaluationReportsTab.tsx`
- `products/ai_observability/frontend/evaluations/components/EvaluationReportConfig.tsx`

Changes:

- Do not show report configuration while creating a sentiment evaluation.
- Do not show report configuration when editing an existing sentiment evaluation.
- If reports live behind a tab, hide or disable that tab for `evaluation_type == "sentiment"`.
- If the active tab is reports and the user switches the eval type to sentiment, move them back to a supported tab.
- Keep the backend as the source of truth by also preventing report creation for non-boolean evaluations.

### 4. Add sentiment execution activity

File:

- `posthog/temporal/ai_observability/run_evaluation.py`

Add an activity like:

```python
@temporalio.activity.defn
async def execute_sentiment_eval_activity(evaluation: dict[str, Any], event_data: dict[str, Any]) -> SentimentEvalResult:
    ...
```

Recommended behavior:

- Validate `evaluation["evaluation_type"] == "sentiment"`.
- Validate `evaluation["output_type"] == "sentiment"`.
- Parse `event_data["properties"]` if it is a JSON string.
- Extract the source event input from `$ai_input`.
- Use `extract_user_messages_individually`.
- Use `truncate_to_token_limit`.
- Use `classify` to classify messages.
- Use `build_generation_result` to produce the same generation-level sentiment shape used by the existing sentiment path.
- Return label, score, scores, messages, message count, and a compact reasoning string.

The eval workflow is generation-oriented today, so the first implementation should classify only the target `$ai_generation`.
Trace-level aggregation can be derived later by grouping generation-level sentiment eval events by `$ai_trace_id`.

### 5. Make workflow dispatch explicit

File:

- `posthog/temporal/ai_observability/run_evaluation.py`

Replace the current `hog`/else branch with explicit runtime handling:

```python
if evaluation_type == "hog":
    result = await execute_hog_eval_activity(...)
elif evaluation_type == "sentiment":
    result = await execute_sentiment_eval_activity(...)
elif evaluation_type == "llm_judge":
    result = await execute_llm_judge_activity(...)
else:
    raise ApplicationError(...)
```

This avoids accidentally sending future eval types through the LLM judge path.

### 6. Split side effects by runtime

File:

- `posthog/temporal/ai_observability/run_evaluation.py`

Changes:

- Increment trial eval count only for `llm_judge`.
- Emit internal LLM telemetry only for `llm_judge`.
- Emit eval signals only for boolean evals, probably `llm_judge` and `hog`.
- Emit LLM cost/model properties only when `evaluation_type == "llm_judge"` and the result was not skipped.

The current check `evaluation_type != "hog"` is too broad once sentiment exists.

### 7. Extend event emission for sentiment

File:

- `posthog/temporal/ai_observability/run_evaluation.py`

Update `emit_evaluation_event_activity` to:

- Keep common `$ai_evaluation` linkage properties.
- Branch on `evaluation_type == "sentiment"` and add `$ai_sentiment_*` properties.
- Avoid `$ai_evaluation_result` for sentiment in this first pass.
- Continue existing boolean result emission for `llm_judge` and `hog`.

### 8. Register the activity

File:

- `posthog/temporal/ai_observability/__init__.py`

Changes:

- Import `execute_sentiment_eval_activity`.
- Add it to `EVAL_ACTIVITIES`.
- Add it to the metrics activity type allowlist in `posthog/temporal/ai_observability/metrics.py`.

### 9. Check worker image/dependency assumptions

Files:

- `Dockerfile.llm-analytics`
- `posthog/management/commands/start_temporal_worker.py`

The sentiment model expects ONNX assets and sentiment Python dependencies.
Before shipping, confirm that the worker process serving `LLMA_EVALS_TASK_QUEUE` uses an image with the sentiment dependency group and baked model.

If not, there are two options:

- Add the sentiment dependency group/model to the eval worker image.
- Keep model inference on the sentiment task queue and have the eval workflow delegate classification there.

The cleaner architecture is to run sentiment inside the eval runtime, but only if the worker image already supports it or can reasonably support it.

### 10. Update automatic scheduler routing

Files:

- `nodejs/src/ai-observability/services/temporal.service.ts`
- `nodejs/src/evaluation-scheduler/evaluation-scheduler.ts`

Changes:

- Add a sentiment workflow ID prefix, for example `llma-sentiment-eval`.
- Treat sentiment like Hog for provider-key gating; sentiment should not require a provider key.
- Add scheduler tests for sentiment dispatch and provider-key bypass.

### 11. Update manual run routing

File:

- `products/ai_observability/backend/api/evaluation_runs.py`

Changes:

- Add a sentiment workflow ID prefix for manual runs.
- Keep the existing event lookup and `RunEvaluationInputs` path.
- Add a test that manual sentiment evals start `run-evaluation` with the sentiment prefix.

### 12. Regenerate API types

Commands likely needed after serializer/model enum changes:

```bash
bin/hogli build:openapi
pnpm --filter=@posthog/mcp run scaffold-yaml -- --sync-all
```

Generated frontend/API/MCP files should change because `EvaluationTypeEnumApi` and `OutputTypeEnumApi` will gain new values.

## Tests

Backend model/API tests:

- `sentiment + sentiment` config validates.
- `sentiment + boolean` is rejected.
- `llm_judge + sentiment` is rejected.
- Sentiment evaluation create/update does not require model config.
- Re-enabling sentiment bypasses trial/BYOK checks.
- Default report configs are not created for sentiment evaluations.
- Evaluation report creation rejects or ignores sentiment evaluations until reports become output-type aware.

Frontend tests:

- Report configuration is hidden while creating a sentiment evaluation.
- Report configuration is hidden when editing a sentiment evaluation.
- Switching an evaluation to sentiment from the reports tab moves to a supported tab.

Temporal tests:

- Workflow dispatch calls sentiment activity for `evaluation_type == "sentiment"`.
- Sentiment activity classifies user messages from `$ai_input`.
- Empty or missing user messages produce a neutral result with `message_count = 0`.
- Event emission writes `$ai_sentiment_*` properties.
- Event emission does not write LLM model/provider/token/key properties for sentiment.
- Event emission does not write `$ai_evaluation_result` for sentiment.
- Trial quota is not incremented for sentiment.
- Internal LLM telemetry is not emitted for sentiment.
- Eval signal emission is not attempted for sentiment.

Node scheduler tests:

- Sentiment evaluations get enqueued when conditions match.
- Sentiment uses the sentiment workflow ID prefix.
- Provider-key gate ignores sentiment evaluations.

Manual run tests:

- Manual sentiment run starts `run-evaluation`.
- Manual sentiment run uses the sentiment workflow ID prefix.

Metrics tests:

- `execute_sentiment_eval_activity` is tracked as an eval activity.
- Sentiment workflow completions are labeled with `evaluation_type = "sentiment"`.
- Sentiment is not counted as `true`, `false`, or `na` verdict unless a future output-type-aware metric is added.

## Open questions

1. Should sentiment evaluations be user-created, system-created, or both?
2. Should the first PR expose sentiment in the evaluation creation UI/API, or only enable backend-created/system-managed sentiment configs?
3. Should sentiment workflow errors disable the evaluation, or just fail that run?
4. Can the eval worker image load the ONNX sentiment model today, or does the worker/deployment setup need to change?

## Suggested first PR boundary

Keep the first PR backend/workflow-only:

- Add `sentiment` enum/config support.
- Add the Temporal sentiment eval activity.
- Emit sentiment-specific `$ai_evaluation` properties.
- Update scheduler/manual run prefixes and provider-key gates.
- Skip/hide evaluation report config for sentiment.
- Add focused tests.

Do not change the current on-read sentiment API or UI readers in this PR.
Those can migrate after sentiment eval events are being emitted reliably.
