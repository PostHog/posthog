# Detector validation results

Recorded on September 16, 2026, with the matched-moment negative-binomial fit and the isolated-spike guard restricted to non-overdispersed baselines.

## Release status

> [!WARNING]
> The short-history chart remains a rollout blocker.
> Passing the regression tests does not mean that six or nine pooled hourly samples support the configured false-flag budget.
> Chart bands and markers are disabled while no validated history policy exists.
> Observed counts remain available, with no promised readiness date.
> Re-enabling bands requires a validated policy or a separately validated short-history model.

The negative-binomial model produces 6.733 false-positive buckets per series per day in the seeded scenario, compared with 64.023 for Poisson.
Its tier A and B info precision is 0.614 and 0.782; their window recall is 1.000 and 0.743.
These are scenario results, not production measurements or a guarantee of the configured budget.
The robust expected-rate estimate still controls silence eligibility; changing that estimate to the untrimmed mean introduces false silences on intermittent streams.

The clean-data sweep uses 40 baseline samples and 500 trials per cell.
The observed negative-binomial false-flag rates range from 0.000 to 0.006 against a nominal two-sided budget of approximately 0.00035.
A sweep with 500 trials per cell cannot establish that small a nominal budget, and several cells exceed it.
The former claim that this establishes calibration across the count range is not supported.

## Short hourly histories

A separate run of the existing `band_calibration_sweep` uses `rate_floor=12`, `alpha=0.05/24`, `seed=10`, `lambdas=(1000.0,)`, `cvs=(0.12, 0.5, 2.2)`, and the default 500 trials.
The nominal two-sided false-flag rate is approximately 0.00417.
With hourly pooling, two, three, and five complete baseline weeks supply six, nine, and fifteen samples respectively.

| Samples | CV 0.12 | CV 0.5 | CV 2.2 |
| ------- | ------- | ------ | ------ |
| 6       | 0.048   | 0.062  | 0.076  |
| 9       | 0.026   | 0.012  | 0.040  |
| 15      | 0.016   | 0.012  | 0.024  |

These results isolate the count model; they do not exercise the chart's level adjustment, neighboring-bucket correlations, or history gate.
Removing the fixed-fraction variance trim fixes a real bias, but it does not account for parameter uncertainty with small samples.
A generic ten-standard-deviation rejection rule also removes legitimate upper-tail samples from variable baselines, so the guard applies only when the remaining samples are not overdispersed.

## Reproduction

The full documented runner completed in a booted Django environment, including the registry-backed scorers, severity widening, persistence ablation, and level-shift experiments:

```sh
python -m products.apm.backend.logic.anomaly_detection.validation.run --weeks 10 --eval-weeks 2 --ephemerals 30 --seed 7
```

The recorded output follows.
The scenario and seed come from the repository's public simulation defaults.

seed=7 weeks=10 eval_weeks=2 series=49 anomalies=133

## Band model bake-off

```
  model: poisson
    verdicts 17998, fp/series/day 64.023
    issues/day median 110.0 p95 121.0, issue precision 0.033 (50/1524)
    silence: windows 34/38 detected, fp persistent 1428, fp ephemeral 0
    tier A info    precision 0.039  window-recall 1.000  tp   264  fp  6436
    tier B info    precision 0.134  window-recall 0.971  tp   289  fp  1863
    tier B warn    precision 0.052  window-recall 1.000  tp   263  fp  4829
    tier C error   precision 0.014  window-recall 0.500  tp    48  fp  3410
    tier C info    precision 0.174  window-recall 0.929  tp   104  fp   492
    stage cold_start  precision 0.714  tp    40  fp    16
    stage developing  precision 0.124  tp    74  fp   521
    stage mature      precision 0.049  tp   854  fp 16493
    (84.5s)

  model: negative_binomial
    verdicts 2515, fp/series/day 6.733
    issues/day median 22.5 p95 25.7, issue precision 0.260 (78/300)
    silence: windows 34/38 detected, fp persistent 1578, fp ephemeral 0
    tier A info    precision 0.614  window-recall 1.000  tp   264  fp   166
    tier B info    precision 0.782  window-recall 0.743  tp   186  fp    52
    tier B warn    precision 0.509  window-recall 0.821  tp   175  fp   169
    tier C error   precision 0.023  window-recall 0.250  tp    31  fp  1331
    tier C info    precision 0.482  window-recall 0.786  tp    68  fp    73
    stage cold_start  precision 0.917  tp    33  fp     3
    stage developing  precision 0.661  tp    37  fp    19
    stage mature      precision 0.270  tp   654  fp  1769
    (40.7s)

  model: mad
    verdicts 6836, fp/series/day 22.929
    issues/day median 28.5 p95 36.4, issue precision 0.217 (80/369)
    silence: windows 30/38 detected, fp persistent 354, fp ephemeral 0
    tier A info    precision 0.582  window-recall 1.000  tp   262  fp   188
    tier B info    precision 0.652  window-recall 0.714  tp   202  fp   108
    tier B warn    precision 0.405  window-recall 0.786  tp   169  fp   248
    tier C error   precision 0.005  window-recall 0.393  tp    28  fp  5437
    tier C info    precision 0.392  window-recall 0.786  tp    76  fp   118
    stage cold_start  precision 0.919  tp    34  fp     3
    stage developing  precision 0.562  tp    45  fp    35
    stage mature      precision 0.098  tp   658  fp  6061
    (88.4s)

  model: zscore
    verdicts 6169, fp/series/day 20.180
    issues/day median 27.0 p95 37.7, issue precision 0.190 (71/373)
    silence: windows 35/38 detected, fp persistent 4787, fp ephemeral 0
    tier A info    precision 0.655  window-recall 1.000  tp   262  fp   138
    tier B info    precision 0.712  window-recall 0.714  tp   200  fp    81
    tier B warn    precision 0.450  window-recall 0.714  tp   165  fp   202
    tier C error   precision 0.020  window-recall 0.607  tp    98  fp  4850
    tier C info    precision 0.439  window-recall 0.786  tp    76  fp    97
    stage cold_start  precision 0.919  tp    34  fp     3
    stage developing  precision 0.616  tp    45  fp    28
    stage mature      precision 0.119  tp   722  fp  5337
    (46.9s)

  model: iqr
    verdicts 4184, fp/series/day 12.921
    issues/day median 51.0 p95 59.0, issue precision 0.112 (79/704)
    silence: windows 33/38 detected, fp persistent 1406, fp ephemeral 0
    tier A info    precision 0.565  window-recall 1.000  tp   262  fp   202
    tier B info    precision 0.663  window-recall 0.714  tp   201  fp   102
    tier B warn    precision 0.419  window-recall 0.750  tp   167  fp   232
    tier C error   precision 0.013  window-recall 0.464  tp    38  fp  2789
    tier C info    precision 0.414  window-recall 0.786  tp    79  fp   112
    stage cold_start  precision 0.919  tp    34  fp     3
    stage developing  precision 0.570  tp    45  fp    34
    stage mature      precision 0.164  tp   668  fp  3400
    (50.4s)

  model: negative_binomial (with severity widening)
    verdicts 2448, fp/series/day 6.586
    issues/day median 21.5 p95 25.7, issue precision 0.251 (74/295)
    silence: windows 34/38 detected, fp persistent 1581, fp ephemeral 0
    tier A info    precision 0.614  window-recall 1.000  tp   264  fp   166
    tier B info    precision 0.782  window-recall 0.743  tp   186  fp    52
    tier B warn    precision 0.479  window-recall 0.714  tp   148  fp   161
    tier C error   precision 0.023  window-recall 0.214  tp    30  fp  1300
    tier C info    precision 0.482  window-recall 0.786  tp    68  fp    73
    stage cold_start  precision 0.917  tp    33  fp     3
    stage developing  precision 0.661  tp    37  fp    19
    stage mature      precision 0.266  tp   626  fp  1730

```

## Band calibration sweep (clean NB data; calibrated ~= 2\*alpha = 3.5e-04)

```
  poisson
    cv=0.12  lam=     1: 0.0000  lam=    10: 0.0000  lam=   100: 0.0020  lam=  1000: 0.3560  lam= 10000: 0.7800
    cv=0.5   lam=     1: 0.0000  lam=    10: 0.0220  lam=   100: 0.4760  lam=  1000: 0.8300  lam= 10000: 0.9580
    cv=2.2   lam=     1: 0.0240  lam=    10: 0.1960  lam=   100: 0.5740  lam=  1000: 0.7780  lam= 10000: 0.8780
  negative_binomial
    cv=0.12  lam=     1: 0.0000  lam=    10: 0.0000  lam=   100: 0.0000  lam=  1000: 0.0020  lam= 10000: 0.0000
    cv=0.5   lam=     1: 0.0000  lam=    10: 0.0000  lam=   100: 0.0000  lam=  1000: 0.0060  lam= 10000: 0.0020
    cv=2.2   lam=     1: 0.0020  lam=    10: 0.0020  lam=   100: 0.0040  lam=  1000: 0.0000  lam= 10000: 0.0020
  mad
    cv=0.12  lam=     1: 0.0380  lam=    10: 0.0020  lam=   100: 0.0060  lam=  1000: 0.0060  lam= 10000: 0.0080
    cv=0.5   lam=     1: 0.0340  lam=    10: 0.0140  lam=   100: 0.0040  lam=  1000: 0.0140  lam= 10000: 0.0220
    cv=2.2   lam=     1: 0.3080  lam=    10: 0.3300  lam=   100: 0.2840  lam=  1000: 0.2640  lam= 10000: 0.2860
  zscore
    cv=0.12  lam=     1: 0.0060  lam=    10: 0.0040  lam=   100: 0.0020  lam=  1000: 0.0020  lam= 10000: 0.0020
    cv=0.5   lam=     1: 0.0040  lam=    10: 0.0020  lam=   100: 0.0020  lam=  1000: 0.0080  lam= 10000: 0.0120
    cv=2.2   lam=     1: 0.0160  lam=    10: 0.0300  lam=   100: 0.0240  lam=  1000: 0.0300  lam= 10000: 0.0240
  iqr
    cv=0.12  lam=     1: 0.0100  lam=    10: 0.0060  lam=   100: 0.0080  lam=  1000: 0.0020  lam= 10000: 0.0060
    cv=0.5   lam=     1: 0.0120  lam=    10: 0.0100  lam=   100: 0.0020  lam=  1000: 0.0080  lam= 10000: 0.0220
    cv=2.2   lam=     1: 0.1200  lam=    10: 0.1200  lam=   100: 0.1320  lam=  1000: 0.1160  lam= 10000: 0.1320
```

## Persistence gate ablation (negative_binomial)

```
  full design                  silence fp ephemeral    0, persistent 1578, opens/day median 22.5
  no persistence gate          silence fp ephemeral  134, persistent 1578, opens/day median 22.5
  naive (no gate, 1h history)  silence fp ephemeral    0, persistent 1176, opens/day median 21.0
```

## Level shift re-baselining (permanent shift, 5 weeks runway)

```
  x2 passive (exclusion cap)      2.6 days (402 verdicts)
  x2 stability test (12 buckets)  0.0 days (12 verdicts)
  x4 passive (exclusion cap)      still firing at run end (7810 verdicts)
  x4 stability test (12 buckets)  0.0 days (12 verdicts)
```
