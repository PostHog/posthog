# Alerts agent guide

## The AI detector (`llm` detector type)

These rules apply when you change the `llm` detector, its gating, its prompt, or any code path that can put an alert on it.
It ships behind the `alerts-llm-detector` flag.

Every other detector is a local statistical test that costs nothing per check.
The AI detector makes a charged model call on every check, so most of these rules bound that cost.

### Cost and gating

- A change that adds a model call to a check needs a cost story first. Calls per day are enabled AI alerts multiplied by cadence ticks per day.
- The AI detector is not available as an ensemble member, on the real-time cadence, or on breakdown insights. Each of these would multiply calls per check, or exceed the evaluate activity's time budget.
- `llm_detector_access_error` (rollout flag plus AI data processing consent) runs in simulate, in every alert writer, and inside the judge on every scheduled check. Keep all three calls. The per-check call is what makes turning the flag off stop the spend.
- The rollout is checked for the alert's creator, because the check runs as the creator. Do not check the last editor.
- Every writer that can put an alert on the AI detector (the API and the Max tool) calls `admit_llm_alert_write` inside its own transaction, after it locks the alert row. Do not add the cadence, access, or cap rules to a writer directly.
- The per-project cap is `max_llm_alerts_per_team` in the flag payload. It counts only enabled AI alerts, and it is checked only on a write that adds one, so lowering it never blocks an edit.
- Simulate with the AI detector is a charged call. It needs `alert:write` and is throttled per project.

### The score is confidence, not probability

- The model returns confidence in its own verdict. It is not calibrated and is not comparable with a statistical detector's score.
- The stored anomaly score is `confidence` for an anomaly verdict and `1 - confidence` for an all-clear. The check also stores the verdict, and history classification reads the verdict, not the score.
- Label the number "model confidence" or "Anomaly confidence" in copy. Never call it a probability.

### Evaluation

- A check that cannot reach a verdict records an error. It never returns "no anomaly", because an alert that silently stops firing looks healthy.
- A live check fires only when the model flags the latest point. A series with fewer than five points is never sent to the model.
- Every detector check stores `detector_type`, `insight_id` and `series_index` as provenance, so an investigation reads the check the way it was produced after the alert changes.
- Metric metadata in the prompt is escaped and marked as data.

### Where the code lives

The judge is not a `BaseDetector`: it reads what the series means and who the call runs as, so it has its own contract.

- Read [`backend/judge/contract.py`](backend/judge/contract.py) when you change the judge's inputs, outputs, or errors.
- Read [`backend/llm_detector_limits.py`](backend/llm_detector_limits.py) when you change write admission, the cap, cadence, or access.
- Read [`backend/evaluation/detector.py`](backend/evaluation/detector.py) when you change how a verdict becomes a check, breach text, or simulate.
- Read [`posthog/tasks/alerts/metric_definition.py`](../../posthog/tasks/alerts/metric_definition.py) and [`charts.py`](../../posthog/tasks/alerts/charts.py) when you change what the model is shown.
