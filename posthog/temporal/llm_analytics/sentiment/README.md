# Sentiment classification

Async sentiment classification for `$ai_generation` events. Classifies each user message individually using a local ONNX model and emits a `$ai_sentiment` event to ClickHouse.

Sentiment is best-effort. Missing a classification is acceptable; blocking the queue or retrying excessively is not.

## How it works

```text
$ai_generation ingested (Kafka)
    |
    v
Node.js consumer starts Temporal workflow (llma-run-sentiment-classification)
    |
    v
classify_sentiment_activity:
  1. Extract user messages from $ai_input (last 50, last 2000 chars each)
  2. Classify each message via ONNX model (cardiffnlp/twitter-roberta-base-sentiment-latest)
  3. Compute overall sentiment as the "worst" label (negative > neutral > positive)
  4. Emit $ai_sentiment event to ClickHouse
```

## Emitted event

The `$ai_sentiment` event carries:

| Property                    | Description                                              |
| --------------------------- | -------------------------------------------------------- |
| `$ai_trace_id`              | Links to the parent trace                                |
| `$ai_session_id`            | Links to the AI session                                  |
| `$ai_parent_id`             | Links to the generation (for trace tree nesting)         |
| `$ai_generation_event_uuid` | UUID of the source generation event                      |
| `$ai_sentiment_label`       | Overall label: `positive`, `neutral`, or `negative`      |
| `$ai_sentiment_score`       | Confidence score of the overall label (0-1)              |
| `$ai_sentiment_scores`      | All three class scores (`{positive, neutral, negative}`) |
| `$ai_sentiment_model`       | Model name used for classification                       |
| `$ai_sentiment_messages`    | Per-message array of `{label, score}` objects            |

## Compute bounds

Controlled in `constants.py`:

- **MAX_USER_MESSAGES = 50** -- only the last 50 user messages are classified
- **MAX_MESSAGE_CHARS = 2000** -- each message is truncated to the last 2000 characters (model limit is 512 tokens)

Both limits take from the tail on the assumption that recent content is more informative.

## Temporal configuration

Sentiment workflows are designed to fail fast rather than retry aggressively.

| Setting                    | Value               | Rationale                          |
| -------------------------- | ------------------- | ---------------------------------- |
| Retry attempts             | 2                   | Low -- better to drop than pile up |
| Retry interval             | 2s initial, 10s max | Quick retry then give up           |
| Activity start_to_close    | 2 min               | Per-attempt wall clock limit       |
| Activity schedule_to_close | 5 min               | Total time including retries       |
| Activity heartbeat         | 30s                 | Detects hung ONNX inference early  |
| Workflow execution timeout | 10 min              | Prevents stuck workflows lingering |

The activity heartbeats after each message classification. If the ONNX model hangs on a single inference, Temporal will detect it within the heartbeat window rather than waiting for the full start_to_close timeout.

## Model

Uses `cardiffnlp/twitter-roberta-base-sentiment-latest` via ONNX Runtime (~60MB) instead of PyTorch (~2GB). The ONNX export is cached to disk (`POSTHOG_SENTIMENT_MODEL_CACHE` env var, defaults to `/tmp/posthog-sentiment-onnx-cache`) so worker restarts skip the initial conversion.

The model is loaded once per worker process (singleton with double-checked locking). A `_classify_lock` (asyncio.Lock) serializes inference calls because the torch ONNX exporter is not thread-safe.

## Files

| File               | Purpose                                                        |
| ------------------ | -------------------------------------------------------------- |
| `constants.py`     | All configuration: model, extraction bounds, Temporal timeouts |
| `extraction.py`    | Extract and truncate user messages from `$ai_input`            |
| `model.py`         | ONNX model loading and inference                               |
| `run_sentiment.py` | Temporal workflow and activity                                 |
| `tests/`           | Unit tests                                                     |

## Task queue

- **Dev**: `development-task-queue`
- **Prod**: `llm-analytics-task-queue`

Configured in `nodejs/src/llm-analytics/services/temporal.service.ts`.

## Running tests

```bash
pytest posthog/temporal/llm_analytics/sentiment/tests/
```
