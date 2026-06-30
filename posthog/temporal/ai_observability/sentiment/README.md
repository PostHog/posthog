# Sentiment classification

Sentiment classification for AI observability workflows.
The classifier analyzes user messages from `$ai_generation` events using an ONNX model
(`cardiffnlp/twitter-roberta-base-sentiment-latest`), and callers persist the result as `$ai_evaluation` events when sentiment is configured as an AI evaluation.

## How it works

Sentiment AI evaluations run through the evaluation workflow, classify the target generation's user messages, and emit stored `$ai_evaluation` events with `$ai_sentiment_*` properties.

The AI observability UI reads stored sentiment evaluation events. It does not trigger on-read sentiment classification.

## Package structure

| File            | Purpose                                                 |
| --------------- | ------------------------------------------------------- |
| `schema.py`     | Dataclasses: `SentimentResult`, `PendingClassification` |
| `model.py`      | ONNX model loading and `classify()`                     |
| `extraction.py` | User message extraction from `$ai_input`                |
| `utils.py`      | Shared helpers for result building and score averaging  |
| `constants.py`  | Model config and extraction caps                        |

## Local development

### Using hogli (recommended)

If you enable the `llm_analytics` intent via `hogli dev:setup`, the sentiment
dependencies and ONNX model download are handled automatically. The temporal-worker
startup prepends `uv sync --group sentiment --inexact && uv run --group sentiment bin/download-sentiment-model`
to its shell command, so no manual steps are needed. Packages are cached by uv,
so re-installs after the first run are fast (~1–2s).

### Manual setup

If you aren't using hogli, install the sentiment dependency group:

```bash
uv sync --group sentiment
```

This pulls in `optimum[onnxruntime]` and `torch` (~2GB).
In production these are pre-installed in `Dockerfile.llm-analytics`.

The ONNX model must be pre-baked — the worker raises `FileNotFoundError`
if it's missing from `ONNX_CACHE_DIR` (default `/tmp/posthog-sentiment-onnx-cache`).
In production the model is baked into the Docker image at build time
(see `Dockerfile.llm-analytics`).

To download the model locally:

```bash
uv run --group sentiment bin/download-sentiment-model
```

This is a no-op if the model already exists.

### Runtime CPU controls

The ONNX Runtime session defaults to one intra-op and one inter-op thread to
avoid CPU oversubscription when Temporal runs multiple evaluation activities
concurrently.
Override these only for a dedicated worker with measured headroom:

```bash
POSTHOG_SENTIMENT_ONNX_INTRA_OP_NUM_THREADS=2
POSTHOG_SENTIMENT_ONNX_INTER_OP_NUM_THREADS=1
```

## Running tests

```bash
pytest posthog/temporal/ai_observability/sentiment/ -x -q
```

Tests mock the model so the sentiment dependency group is not required to run them.

## UI data flow

The Sentiment tab and trace/generation sentiment displays read `$ai_evaluation` events where `$ai_evaluation_runtime = 'sentiment'`.
If a project has no sentiment evaluation configured, the Sentiment tab shows onboarding instead of running classification on read.
