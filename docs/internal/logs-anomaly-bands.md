# Logs anomaly bands

The Logs **Anomalies** tab shows observed counts.
Expected ranges and anomaly markers are disabled until a validated history policy is defined.
The chart labels the expected range as unavailable and does not promise a readiness date.
Once a validated policy exists, the chart can compare counts against a modeled expected range.
The range is not the minimum and maximum seen in previous weeks.
The response keeps the existing `lower`, `upper`, and `verdict` fields.

## Baseline and count model

The chart pools the same time of week and nearby buckets from up to five previous weeks.
There is no validated maturity threshold for enabling these bands.
The readiness gate therefore remains closed for every history depth, including the full five-week lookback.
Missing buckets inside a series' lifetime contribute zero; times before that lifetime do not.
A guarded trailing-day level adjustment lets the range follow a sustained change without immediately absorbing a spike.
Quiet series have a lower bound of zero, so quiet hours are not marked as drops.

The chart and anomaly scan use the same negative-binomial band model.
They do not promise identical verdicts: display grain, history depth, pooling, and the scan's persistence and exclusion gates differ.

The negative-binomial distribution's mean and sample variance use the same observations.
The model does not trim a fixed fraction from each tail, which would underestimate genuine count variability.
For at least five samples, it screens the largest observation against the remaining samples.
It removes that observation only when the remaining samples are not overdispersed and the observation exceeds their mean by ten Poisson-floor standard deviations.
It does not remove an upper-tail observation from an already overdispersed baseline.
This isolated-spike heuristic is not a calibrated outlier probability or a general treatment of contaminated history.
The model retains the other observations and uses a Poisson band when they are not overdispersed.
The returned `expected` value keeps the detector's trimmed-mean estimate of typical traffic.
The silence gate uses that estimate so occasional bursts do not make an otherwise quiet stream appear continuously active.
The interval fit uses the untrimmed moments of the retained observations, not that silence-gate estimate.

## Cost

The chart chooses each series' final display grain before fitting its bands.
Discarded coarsening candidates and series beyond the response cap do not need fitted bands.
Quantiles run in NumPy/SciPy batches per returned series instead of separate SciPy calls for every bucket.
The scalar scan and batched chart paths share the moment estimator and have an equality regression test.

## Validation and rollout

The [detector validation report](../../products/apm/backend/logic/anomaly_detection/validation/REPORT.md) records the full calibration command and its limitations.
The simulation is evidence about the modeled scenarios, not a guarantee that real traffic meets the configured false-flag budget.
Six or nine pooled hourly samples do not support the configured false-flag budget.
The two-week gate is no longer used as evidence of readiness.
Bands cannot be enabled merely by passing `include_bands=True`; the validated-history gate must also pass.
Correlated neighboring buckets and sustained shifts also need review with representative services.

Before broad rollout, compare normal seasonal traffic, isolated spikes, sustained drops, and quiet services at both hourly and finer grains.
Check that ordinary variability stays inside the band while clear spikes and drops remain visible.
Monitor the series-bands endpoint's latency and errors, and review scan output because the estimator is shared.
The API response shape and observed counts do not change.
