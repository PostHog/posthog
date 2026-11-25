---
name: working-on-ai-observability
description: >
  Gives the AI observability team's rules for layered code and for bridging it to older code.
  Use before a change or a review in `products/ai_observability/` that adds or changes a capability,
  a resource, a list, a background job or a component in the product's layers (mode B or C in the
  product's AGENTS.md), or that connects new code to old code.
  Applies to AI observability only. Trigger terms: AI observability, AIO, llma, LLM analytics.
---

# Working on AI observability

This is how the AI observability team works in its own product.
It sets no rule for other products.

[`products/ai_observability/AGENTS.md`](../../../products/ai_observability/AGENTS.md) holds the six principles, the three modes and the layer table.
Read it first if it is not already loaded, and pick your mode there.
This skill is the detail for modes B and C.
Each rule gives its reason in the same line.

## Read only what you touch

| You are                                                                   | Read                                             |
| ------------------------------------------------------------------------- | ------------------------------------------------ |
| Adding or changing backend code in the layers                             | [references/backend.md](references/backend.md)   |
| Adding or changing frontend code in the layers                            | [references/frontend.md](references/frontend.md) |
| Connecting new code to old code, replacing old code, or moving a resource | [references/old-code.md](references/old-code.md) |

## Copy these

Paths are relative to `products/ai_observability/`.

| Shape                    | Example                                                                                                                                                                          |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Read from Postgres       | `backend/presentation/views/trace_review.py`, `get_trace_review_status` in `backend/facade/api.py`, `backend/logic/traces/review.py`, `backend/logic/traces/review_queries.py`   |
| Read from ClickHouse     | `backend/presentation/views/trace_evaluations.py`, `get_trace_evaluation_results` in `backend/facade/api.py`, `backend/logic/traces/evaluation_result.py` and its `_queries.py`  |
| Write that starts a job  | `backend/presentation/views/trace_summary.py`, `request_trace_summary` in `backend/facade/api.py`, `backend/logic/traces/summary.py`, `backend/temporal/trace_summary_client.py` |
| Nested resource          | `backend/presentation/views/trace_resource.py` as the shared base, with `backend/presentation/views/trace_review.py`                                                             |
| Edge-case path           | `backend/logic/traces/events_fallback.py`                                                                                                                                        |
| Component with its logic | `frontend/redesign/trace/traceFeedbackLogic.ts`, `frontend/redesign/trace/hosts/TraceFeedbackHost.tsx`, `frontend/redesign/trace/components/TraceFeedbackView.tsx`               |

## Before you report done

- The change is in one mode, and you can name it.
- Each layer you touched has its own tests: behavior without a database, the facade function once, the view for parsing and permissions only.
- `hogli build:openapi` ran after a serializer or contract change.
- `hogli product:lint ai_observability` passes. It fails a presentation module that imports `models/`.
- The answer to each of the six questions is yes.
