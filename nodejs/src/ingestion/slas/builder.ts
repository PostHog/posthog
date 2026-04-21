import { Gauge, Histogram } from 'prom-client'

import { AGREEMENT_KIND, IndicatorGroup, IndicatorName, OBJECTIVE_KIND, SlaKind } from '../common/slas'
import { getOrCreateSlaTargetGauge, getOrCreateSliHistogram } from './metrics'
import { IndicatorHandle, TargetSpec } from './types'

export interface IngestionSlaLabels {
    pipeline: string
    lane: string
}

type TargetGauge = Gauge<'pipeline' | 'lane' | 'sli' | 'name' | 'kind' | 'le'>
type SliHistogram = Histogram<'pipeline' | 'lane' | 'sli'>

interface TargetEntry {
    name: string
    thresholdMs: number
    targetRatio: number
    kind: SlaKind
}

/**
 * Builder for ingestion SLIs/SLOs/SLAs.
 *
 * SLIs are collected into **indicator groups** — each group is backed by its
 * own Prometheus histogram with a fixed bucket set. `group(group, callback)`
 * scopes the nested callback to that group, letting it declare indicators
 * and their objectives/agreements; thresholds are constrained at compile
 * time to the group's bucket tuple.
 *
 * `.build(labels)` binds pipeline/lane labels, materializes one histogram
 * per declared group, and emits the target gauge entries.
 *
 * @example
 * ```ts
 * export function createSlaRegistry() {
 *     return new IngestionSlaBuilder()
 *         .group(INGESTION_LATENCY_GROUP, (latency) =>
 *             latency.indicator(INGESTION_LAG_INDICATOR, (ingestionLag) =>
 *                 ingestionLag
 *                     .objective('under_5s', { thresholdMs: 5000, targetRatio: 0.999 })
 *                     .agreement('under_60s', { thresholdMs: 60000, targetRatio: 0.99 })
 *             )
 *         )
 * }
 * ```
 */
export class IngestionSlaBuilder<I extends IndicatorName = never> {
    constructor(private readonly groups: GroupBuilderMap = new Map()) {}

    group<const G extends IndicatorGroup<readonly number[]>, NewI extends IndicatorName>(
        group: G,
        callback: (builder: IndicatorGroupBuilder<G>) => IndicatorGroupBuilder<G, NewI>
    ): IngestionSlaBuilder<I | NewI> {
        const seed =
            (this.groups.get(group.name) as IndicatorGroupBuilder<G> | undefined) ?? new IndicatorGroupBuilder<G>(group)
        const next = callback(seed)
        const groups: GroupBuilderMap = new Map(this.groups)
        groups.set(group.name, next as IndicatorGroupBuilder<IndicatorGroup<readonly number[]>, IndicatorName>)
        return new IngestionSlaBuilder<I | NewI>(groups)
    }

    build(labels: IngestionSlaLabels): IngestionSlas<I> {
        const gauge = getOrCreateSlaTargetGauge()
        const handles = new Map<IndicatorName, IndicatorHandle>()
        for (const groupBuilder of this.groups.values()) {
            groupBuilder.materialize(labels, gauge, handles)
        }
        return new IngestionSlas<I>(handles)
    }
}

/**
 * Per-group builder passed to the `group` callback.
 *
 * Accumulates indicator names into `I`. Each indicator shares the group's
 * histogram and buckets.
 */
export class IndicatorGroupBuilder<G extends IndicatorGroup<readonly number[]>, I extends IndicatorName = never> {
    constructor(
        private readonly group: G,
        private readonly indicators: Map<
            IndicatorName,
            IndicatorBuilder<G['buckets'], IndicatorName, string>
        > = new Map()
    ) {}

    indicator<NewI extends IndicatorName>(
        name: NewI & (NewI extends I ? never : NewI),
        callback: (sli: IndicatorBuilder<G['buckets'], NewI>) => IndicatorBuilder<G['buckets'], NewI, string>
    ): IndicatorGroupBuilder<G, I | NewI> {
        const builder = callback(new IndicatorBuilder<G['buckets'], NewI>(name, this.group.buckets))
        const indicators: Map<IndicatorName, IndicatorBuilder<G['buckets'], IndicatorName, string>> = new Map(
            this.indicators
        )
        indicators.set(name, builder as IndicatorBuilder<G['buckets'], IndicatorName, string>)
        return new IndicatorGroupBuilder<G, I | NewI>(this.group, indicators)
    }

    /** Internal — called by `IngestionSlaBuilder.build`. */
    materialize(labels: IngestionSlaLabels, gauge: TargetGauge, handles: Map<IndicatorName, IndicatorHandle>): void {
        const histogram = getOrCreateSliHistogram(this.group.name, this.group.help, this.group.buckets)
        for (const [sli, indicator] of this.indicators) {
            indicator.materialize(labels, gauge)
            handles.set(sli, makeHandle(histogram, labels, sli))
        }
    }
}

/**
 * Per-indicator builder passed to the `indicator` callback.
 *
 * Accumulates objective/agreement names into `N`. Both `objective` and
 * `agreement` share the same `N`, so a name can't be reused across the two
 * for a single indicator.
 */
export class IndicatorBuilder<B extends readonly number[], I extends IndicatorName, N extends string = never> {
    constructor(
        private readonly name: I,
        private readonly buckets: B,
        private readonly targets: TargetEntry[] = []
    ) {}

    objective<NewName extends string>(
        name: NewName & (NewName extends N ? never : NewName),
        spec: TargetSpec<B>
    ): IndicatorBuilder<B, I, N | NewName> {
        return new IndicatorBuilder<B, I, N | NewName>(this.name, this.buckets, [
            ...this.targets,
            { name, thresholdMs: spec.thresholdMs, targetRatio: spec.targetRatio, kind: OBJECTIVE_KIND },
        ])
    }

    agreement<NewName extends string>(
        name: NewName & (NewName extends N ? never : NewName),
        spec: TargetSpec<B>
    ): IndicatorBuilder<B, I, N | NewName> {
        return new IndicatorBuilder<B, I, N | NewName>(this.name, this.buckets, [
            ...this.targets,
            { name, thresholdMs: spec.thresholdMs, targetRatio: spec.targetRatio, kind: AGREEMENT_KIND },
        ])
    }

    /** Internal — called by `IndicatorGroupBuilder.materialize`. */
    materialize(labels: IngestionSlaLabels, gauge: TargetGauge): void {
        for (const target of this.targets) {
            gauge
                .labels({
                    ...labels,
                    sli: this.name,
                    name: target.name,
                    kind: target.kind,
                    le: String(target.thresholdMs),
                })
                .set(target.targetRatio)
        }
    }
}

/**
 * Built SLA container. Pipeline steps get an `IndicatorHandle` via `indicator()`
 * and call `observe(valueMs)` on it per event.
 */
export class IngestionSlas<I extends IndicatorName> {
    constructor(private readonly handles: Map<IndicatorName, IndicatorHandle>) {}

    indicator(name: I): IndicatorHandle {
        const handle = this.handles.get(name)
        if (!handle) {
            // Unreachable when `I` is correctly narrowed — the type system only
            // admits indicator names registered at build time.
            throw new Error(`No handle for indicator ${name}`)
        }
        return handle
    }
}

type GroupBuilderMap = Map<string, IndicatorGroupBuilder<IndicatorGroup<readonly number[]>, IndicatorName>>

function makeHandle(histogram: SliHistogram, labels: IngestionSlaLabels, sli: string): IndicatorHandle {
    const sliLabels = { ...labels, sli }
    return {
        observe(valueMs: number): void {
            histogram.labels(sliLabels).observe(valueMs)
        },
    }
}
