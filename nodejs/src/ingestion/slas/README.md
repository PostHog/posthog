# Ingestion SLAs

Declarative framework for ingestion **indicator groups**, **SLIs**, **SLOs**,
and **SLAs**. The framework emits Prometheus metrics and provides a Grafana
panel that adapts automatically to the declared targets given only `pipeline`
and `lane`.

## Vocabulary

- **Indicator group** — a metric-level definition (name, help, unit, buckets)
  backed by a single Prometheus histogram. Different groups have independent
  bucket sets; different groups → different histograms.
- **SLI** (indicator) — a named measurement within a group. Many SLIs can
  share one group and are distinguished by the `sli` label.
- **SLO** — an internal objective expressed as "X% of events under Y ms".
  Emitted as `kind="objective"` on the target gauge.
- **SLA** — an external agreement, same shape as an SLO but with
  `kind="agreement"`, so alerting can treat them differently.

## Metrics

```text
<group.name>_bucket{pipeline, lane, sli, le}                        # one histogram per group
ingestion_slo_target_ratio{pipeline, lane, sli, name, kind, le}     # one shared gauge
```

`le` on the target gauge mirrors the histogram's bucket label, so the panel
joins target→bucket on `on(pipeline, lane, sli, le)` with no label surgery.

The histogram name is the group's `name` field verbatim. Follow the
`ingestion_sli_<family>_<unit>_histogram` naming convention so the shared
Grafana panel can discover all SLI metrics via `__name__=~...` regex.

## Declaring targets

Each pipeline owns its declarations in `<pipeline>/slas/registry.ts`,
analogous to `<pipeline>/outputs/registry.ts`.

```ts
// ingestion/analytics/slas/registry.ts
import { INGESTION_LAG_INDICATOR, INGESTION_LATENCY_GROUP } from '../../common/slas'
import { IngestionSlaBuilder } from '../../slas/builder'

export function createSlaRegistry() {
    return new IngestionSlaBuilder().group(INGESTION_LATENCY_GROUP, (latency) =>
        latency.indicator(INGESTION_LAG_INDICATOR, (ingestionLag) =>
            ingestionLag
                .objective('under_5s', { thresholdMs: 5000, targetRatio: 0.999 })
                .objective('under_10s', { thresholdMs: 10000, targetRatio: 0.99 })
                .objective('under_30s', { thresholdMs: 30000, targetRatio: 0.99 })
                .agreement('under_60s', { thresholdMs: 60000, targetRatio: 0.99 })
        )
    )
}
```

Buckets belong to the indicator group. Every SLI under a `group(...)` block
shares those buckets and is measured into the same histogram.

At service startup, the consumer binds pipeline/lane labels:

```ts
this.slas = createSlaRegistry().build({
    pipeline: this.config.INGESTION_PIPELINE ?? 'unknown',
    lane: this.config.INGESTION_LANE ?? 'unknown',
})
```

## Observing values

Pipeline steps receive an `IndicatorHandle` narrowed to one indicator:

```ts
const lagObserver = slas.indicator(INGESTION_LAG_INDICATOR)
lagObserver.observe(lagMs)
```

The dedicated `reportSlisStep` (see
`ingestion/event-processing/report-slis-step.ts`) does this as an explicit,
testable pipeline step, so observation is not entangled with emit-time logic.

## Compile-time checks

- `thresholdMs` must be one of the indicator group's buckets (literal union
  from the `as const` tuple on the group).
- Objective/agreement names are unique within an indicator.
- Indicator names are unique within a group.
- `slas.indicator(name)` only accepts indicators declared in this registry.

## Grafana panel

`grafana/sli-slo-panel.json` depends only on `$pipeline` and `$lane`
variables. It renders one series per `(sli, name, kind)` with the measured
compliance ratio. The target ratio from the gauge is available for alerts
or a secondary overlay.

## Adding a new indicator

1. Add a constant and type to `ingestion/common/slas/index.ts`, extend `IndicatorName`.
2. Inside the matching `group(GROUP, g => ...)` block in the pipeline's
   `slas/registry.ts`, call `g.indicator(...)` (give the param a name that
   describes the group — e.g. `latency`).
3. If its measurement shape doesn't match any existing group, add a new
   `IndicatorGroup` constant and a new `group(...)` block.
4. Add an observation site — either in `reportSlisStep` (if applicable to
   every event) or in a new step specific to the indicator.
