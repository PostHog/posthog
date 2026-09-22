# Logs anomaly bands

The Logs **Anomalies** tab shows observed counts and calibrated expected ranges.
The ranges target 99% marginal coverage of individual buckets when historical and future traffic follow comparable patterns.
An out-of-range point is a reason to investigate, not a confirmed incident or an alert.
This is not a 99% guarantee that every point in a chart stays inside its range.
The API keeps the existing `lower`, `upper`, and `verdict` fields.

## History and readiness

The volume rollup keeps each bucket for at least 42 days or until its latest raw-log expiry, whichever is later.
The lifetime is measured from the five-minute bucket start and rounded up to whole days, so timestamp skew and bucket rounding cannot shorten it.
A 3650-day guard bounds corrupt expiry values, and rows written before the retention migration keep the 42-day floor.
Rows can expire independently within a shared part; deletion happens during ClickHouse merges, not at an exact wall-clock deadline.

Storage retention does not extend the chart's supported date range by itself.
The chart still limits the start of a displayed window to 35 days ago; longer history needs a separate reader, API, and UI change.
The on-demand anomaly scan queries raw logs rather than this rollup, so this storage change does not extend its history.

The chart uses complete UTC weeks before the displayed window, up to the five-week lookback.
It needs at least four complete weeks: two to fit the weekly pattern and count variability, followed by two separate weeks to calibrate the prediction errors.
With five available weeks, three train the model and two calibrate it.
Neither stage reads observations from the displayed window.
Missing buckets inside the series' sustained lifetime count as zero.
Buckets before that lifetime do not enter the model.

At hourly grain, the two calibration weeks provide 336 errors.
Finer grains provide more errors, not necessarily more independent information.
The implementation rejects calibration sets too short for the finite-sample quantile instead of interpolating an unsupported percentile.
The four-week minimum is a requirement of this train/calibration split, not a claim that age alone makes any traffic pattern predictable.

Younger series still show observed counts and the amount of earlier history they need.
`band_ready_at` gives the earliest end of a rolling window of the same length with enough preceding history.
Waiting does not add earlier history to a fixed historical window; select a more recent window instead.
Retention can also limit the history available to an older window.

## Count model and calibration

The model is local to Logs charts.
It does not change the anomaly scan's detector, persistence rules, or alert budget.

The fitting stage estimates each time-of-week slot's mean from the training weeks.
It pools the within-slot sample variances to estimate a series-wide negative-binomial dispersion:

```text
dispersion = max(0, sum(slot_variance - slot_mean)) / max(1, sum(slot_mean ** 2))
expected = max(1, (sum(slot_training_counts) + mean(all_training_counts) * dispersion)
                  / (training_weeks + dispersion))
```

The second expression shrinks noisy, short-history slot means toward the series mean.
Without shrinkage, a few zero training observations can produce unreasonable predictions for a variable stream.
The model starts with the 5th and 95th percentiles of the fitted count distribution.
It falls back to Poisson when fitted dispersion is negligible.
These initial bounds are not advertised as calibrated probabilities.

The calibration stage applies conformalized quantile regression to `log1p(count)`:

```text
score = max(log1p(initial_lower) - log1p(observed),
            log1p(observed) - log1p(initial_upper))
rank = ceil((number_of_calibration_buckets + 1) * 0.99)
expansion = sorted_scores[rank - 1]
lower = expm1(log1p(initial_lower) - expansion)
upper = expm1(log1p(initial_upper) + expansion)
```

Using an order statistic rather than an interpolated percentile accounts for finite calibration sample size.
The logarithmic score adjusts the asymmetric count interval multiplicatively.
Calibration can widen an overconfident interval or shrink an unnecessarily broad one.
For a slot whose interval would become empty, the expansion stops at the midpoint in log space.
This only enlarges the conformal prediction set.
Bounds are clipped at zero and rounded outward to integers.
An isolated extreme calibration observation does not determine the 99% order statistic across two complete weeks.

The finite-sample coverage result requires exchangeable calibration and future scores conditional on the fitted model.
Time-series residuals are not automatically exchangeable.
Weekly seasonality, serial dependence, changing variance, deployments, and daylight-saving shifts can violate the assumptions.
The target is therefore checked empirically, not presented as an unconditional production guarantee.
See [Conformalized Quantile Regression](https://arxiv.org/abs/1905.03222) for the split-conformal construction.

## Validation

Run the deterministic, synthetic chronological holdout suite:

```sh
uv run python -m products.logs.backend.series_prediction_validation --trials 1000 --seed 20260919
```

Each trial generates training weeks, subsequent calibration weeks, and a separate future test week.
The test week does not fit or calibrate the model.
Cases cover four and five weeks of history, sparse and high-volume counts, Poisson and overdispersed noise, daily and weekly seasonality, cron peaks, correlated noise, occasional bursts, and 5-, 15-, and 60-minute grains.
Spike and drop checks replace test observations with five times or one tenth of the known simulated expectation.

The runner reports the missed-bucket fraction and its standard error across independent simulated histories.
It also reports spike/drop recall, interval width, and fit time.
Its calibration regression threshold requires the approximate 95% upper confidence limit on misses to be at most 1.5%, against the 1% target.
This tolerance detects material miscalibration without pretending a finite simulation proves exactly 99% coverage.
For high-volume, low-variability scenarios, both injected-change recall checks must reach 95%.
Highly variable sparse counts can legitimately have a zero lower bound and a broad upper bound; small changes cannot reliably be distinguished from their normal noise.

Integration tests cover observed-count accuracy, missing-history zeros, short windows using complete calibration weeks, grain coarsening, readiness boundaries, and sustained drops that cannot redefine their own baseline.
The existing scan validation report describes a different model and must not be used as evidence for these chart ranges.

The command above passed all 25 scenarios with 1,000 independently generated histories per scenario.
Observed missed-bucket fractions ranged from 0.11% to 0.97%; correlated traffic had the highest rate (0.97%, standard error 0.037 percentage points).
All required high-volume, low-variability spike and drop checks exceeded 99.99% recall.
Occasional bursts reduced spike recall to 97.17%.
Sparse or highly variable traffic had much lower power, sometimes no detectable injected drops and very broad intervals.
These are synthetic results, not measured production accuracy or proof of useful ranges for every service.

## Cost and rollout

The chart fits only the selected series at their final display grains.
Each fit batches one week's count quantiles, reusing them for calibration and display.
No extra database query or external model service is needed.
The existing `logs-anomalies` feature flag remains the rollout control; this change does not broaden its audience.

Synthetic validation is not a substitute for reviewing real services.
Before a broader rollout, backtest representative services on held-out periods, label normal traffic and known incidents, and inspect coverage and usefulness separately.
Track series-bands latency and errors through the existing query tagging and error reporting.
Long-correlated regime changes, UTC/DST misalignment, heavy contamination, and changes in traffic shape remain limitations to review.
