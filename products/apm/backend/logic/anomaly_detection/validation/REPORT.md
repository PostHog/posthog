# Detector validation results

Run: `python -m products.apm.backend.logic.anomaly_detection.validation.run --weeks 10 --eval-weeks 2 --ephemerals 30 --seed 7`
(49 series seeded from the calibration defaults in calibration.py — production-shaped, with absolute volumes rounded — 133 injected anomalies over a 2-week eval window that crosses the 2026-03-08 US DST shift; requires a booted Django env for the registry-backed scorers.)

## Band model recommendation: negative binomial, no severity widening

- **negative_binomial**: 6.7 fp/series/day, tier A info precision 0.61 and tier B info 0.78 at window-recall 0.71–1.0. Best on every persistent info/warn group, and the **only model calibrated across the count range**: on clean NB data at lambda 1–10,000 x CV {0.12, 0.5, 2.2} its false-flag rate stays at 0.000–0.006, near the 3.5e-4 target.
- **poisson**: 64 fp/series/day — rejected decisively, and the overdispersion answer is broader than the error-severity headline: high-volume `info` series run several times the dispersion Poisson predicts at their rate, and because absolute overdispersion grows with volume, Poisson's sweep false-flag rate climbs to 0.36–0.78 at lambda >= 1,000 _even at CV 0.12_. The design's illustrative Poisson band does not survive contact with realistic data.
- **mad / zscore / iqr** (registry scorers): 23 / 20 / 13 fp/series/day in the scenario; in the sweep MAD and IQR blow up on overdispersed series (26–33% and 12–13% false-flag at CV 2.2) and all three are structurally symmetric — the lower band goes negative at low rates, making drops undetectable per-bucket.
- **Severity widening is off by default**: NB measures dispersion from the samples, so the per-severity multiplier only costs recall (tier B warn window-recall 0.82 → 0.71 with widening, FP essentially unchanged). The multiplier mechanism remains in config for assumed-dispersion models.

## Baseline stages: cold start is usable — mature is where the FPs are

Per-stage precision with NB: cold start 0.92, developing 0.66, mature 0.27. The pre-registered fear was cold start dominating false positives; the widened cold bands are in fact the cleanest, and the FP mass sits in mature series (dominated by the error-severity failure below). Cold-start bands are usable from ~3 days of history.

## Error severity is not per-bucket detectable — every model fails

Error-severity series at single-digit per-bucket rates with CV ~2: best precision 0.023 (NB), NB recall 0.25, MAD emits 5,437 FPs. At that dispersion a 5x spike sits inside the noise. Per-bucket band scoring is the wrong instrument for error streams at these rates; the dials follow-up should score error/fatal on coarser windows (30–60 min) or a presence-based instrument. Related: residual persistent-silence FPs (~1,600/2w across 49 series) concentrate in low-rate high-CV series whose seasonal expectation clears `silence_min_expected` while their natural P(0) is large — the silence candidacy gate should become dispersion-aware in the same follow-up.

## Persistence gate: reproduced

Ephemeral-pod silence FPs over 2 weeks with NB: **0 with the full design vs 134 without the persistence gate**. Two structural notes the original characterization's framing didn't separate: (1) the staged-baseline min-history requirement already suppresses pods younger than ~3 days on its own (birth-side), so the explicit gate's marginal value is bounding the post-death firing window (death-side); (2) multi-day pods' deaths are genuinely indistinguishable from dead workers at death time — that is the irreducible residual, bounded by `persistence_recent_buckets`.

## Level-shift re-baselining: the ~4-week claim is corrected, in both directions

- A x2 shift (within `level_factor_clamp`) is absorbed by the slow level component in **~2.6 days** — much faster than 4 weeks.
- A x4 shift **never passively re-baselines** (still firing after 5 weeks): mature baselines sample the same time-of-week only ~5 buckets/week, and verdict-exclusion feedback keeps new-level samples out, so the exclusion cap's readmission cannot catch up.
- The stability test (12 consecutive same-direction verdicts → re-anchor the baseline window at the shift) goes quiet in **1 hour** at the cost of re-learning from scratch. It should ship; passive re-baselining alone is not a viable story for shifts beyond the level clamp.

## Bug found by the harness: baseline self-legitimization

The trailing edge of the developing/mature pools included buckets minutes before the scored one, so an ongoing incident's own (unflagged) buckets entered the baseline, inflated the dispersion estimate, and blinded the detector within ~4 hours of onset. Fixed with `baseline_guard_buckets` (default 1 day): baselines and the level factor only see data at least a guard period old. `test_ongoing_incident_does_not_legitimize_itself` pins it.

## Caveats

- Injection density (~9.5 anomalies/day across the population) is set for measurement power, not realism — the issues/day numbers here are not directly comparable to the "median ≤1 new issue/day" launch gate, which shadow evaluates at organic anomaly rates.
- The calibration values are rounded representative defaults modeled on internal measurements of production-shaped log traffic; they are calibrating defaults, not universals. The noise model is swappable (`simulation.NoiseModel`) for design-partner data.
- Persistence-gate dial tuning (window/recency sweeps) is deliberately left to the dial-setting follow-up; this run fixes the mechanism and reproduces its effect.
