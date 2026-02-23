# Sentiment classification

On-demand sentiment analysis for LLM Analytics traces.
Classifies user messages from `$ai_generation` events using an ONNX model
(`cardiffnlp/twitter-roberta-base-sentiment-latest`).

## How it works

1. Frontend calls the sentiment API with one or more trace IDs
2. Django starts a Temporal workflow (`llma-sentiment-classify`)
3. The activity fetches `$ai_generation` events via HogQL,
   extracts user messages, and classifies them in a single batch
4. Results are cached (24h TTL) and returned to the frontend

## Package structure

| File            | Purpose                                                                           |
| --------------- | --------------------------------------------------------------------------------- |
| `schema.py`     | Dataclasses: `ClassifySentimentInput`, `SentimentResult`, `PendingClassification` |
| `workflow.py`   | Temporal workflow definition                                                      |
| `activities.py` | Temporal activity (orchestration)                                                 |
| `data.py`       | HogQL query execution and row grouping                                            |
| `model.py`      | ONNX model loading and `classify()`                                               |
| `extraction.py` | User message extraction from `$ai_input`                                          |
| `utils.py`      | Shared helpers: result building, date resolution, score averaging                 |
| `constants.py`  | Config values, caps, and the HogQL query template                                 |
| `metrics.py`    | Prometheus metrics and Temporal interceptor                                       |

## Local development

Install the sentiment dependency group:

```bash
uv sync --group sentiment
```

This pulls in `optimum[onnxruntime]` and `torch` (~2GB).
In production these are pre-installed in `Dockerfile.llm-analytics`.

The ONNX model is downloaded on first use and cached to `ONNX_CACHE_DIR`
(default `/tmp/posthog-sentiment-onnx-cache`).
In production the model is baked into the Docker image at build time.

## Running tests

```bash
pytest posthog/temporal/llm_analytics/sentiment/ -x -q
```

Tests mock the model and HogQL layer so the sentiment dependency group
is not required to run them.

## API endpoints

- `POST /api/environments/:team_id/llm_analytics/sentiment/` -- single trace
- `POST /api/environments/:team_id/llm_analytics/sentiment/batch/` -- up to 25 traces
