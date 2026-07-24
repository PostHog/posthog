import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { Experiment, FilterLogicalOperator } from '~/types'

import { experimentsSessionContextsCreate } from 'products/experiments/frontend/generated/api'

import { getViewRecordingFiltersForVariant } from '../utils'
import { RETENTION_UNLINKABLE_REASON } from '../viewRecordingsLinkabilityLogic'
import { experimentReplayTabLogic } from './experimentReplayTabLogic'

jest.mock('lib/utils/product-intents', () => ({
    addProductIntentForCrossSell: jest.fn().mockResolvedValue(null),
}))

jest.mock('products/experiments/frontend/generated/api', () => ({
    experimentsSessionContextsCreate: jest.fn().mockResolvedValue({ results: [] }),
}))

const PURCHASE_METRIC = {
    kind: NodeKind.ExperimentMetric,
    metric_type: ExperimentMetricType.MEAN,
    uuid: 'metric-purchase',
    name: 'Purchase',
    source: { kind: NodeKind.EventsNode, event: 'purchase' },
}

const FUNNEL_METRIC = {
    kind: NodeKind.ExperimentMetric,
    metric_type: ExperimentMetricType.FUNNEL,
    uuid: 'metric-funnel',
    name: 'Checkout funnel',
    series: [
        { kind: NodeKind.EventsNode, event: 'server_side_step' },
        { kind: NodeKind.EventsNode, event: 'client_step' },
    ],
}

const EXPERIMENT = {
    id: 42,
    feature_flag_key: 'my-flag',
    start_date: '2026-01-01T00:00:00Z',
    end_date: '2026-02-01T00:00:00Z',
    exposure_criteria: { filterTestAccounts: true },
    metrics: [PURCHASE_METRIC],
    metrics_secondary: [FUNNEL_METRIC],
    feature_flag: {
        filters: {
            multivariate: {
                variants: [
                    { key: 'control', rollout_percentage: 50 },
                    { key: 'test', rollout_percentage: 50 },
                ],
            },
        },
    },
} as unknown as Experiment

const ALL_LINKABLE = {
    $feature_flag_called: true,
    purchase: true,
    server_side_step: true,
    client_step: true,
}

describe('experimentReplayTabLogic', () => {
    let logic: ReturnType<typeof experimentReplayTabLogic.build>
    let seenTogetherSpy: jest.SpyInstance

    beforeEach(() => {
        // The facet reducer is persisted; clear so no test inherits another's selection.
        localStorage.clear()
        initKeaTests()
        ;(experimentsSessionContextsCreate as jest.Mock).mockClear()
        seenTogetherSpy = jest.spyOn(api.propertyDefinitions, 'seenTogether')
        seenTogetherSpy.mockResolvedValue(ALL_LINKABLE)
        logic = experimentReplayTabLogic({ experiment: EXPERIMENT })
        logic.mount()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('defaults to the "All" facet and lists the experiment variants', async () => {
        await expectLogic(logic).toMatchValues({
            selectedVariantKey: null,
            variantKeys: ['control', 'test'],
        })
    })

    it('builds an exposure-only filter pinned to the run window', () => {
        const { recordingsFilters } = logic.values

        expect(recordingsFilters.date_from).toBe('2026-01-01T00:00:00Z')
        expect(recordingsFilters.date_to).toBe('2026-02-01T00:00:00Z')
        expect(recordingsFilters.filter_test_accounts).toBe(true)
        // All facet: the inner filter is the exposure helper's "all variants" output, nothing metric-shaped.
        expect(recordingsFilters.filter_group).toEqual({
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: FilterLogicalOperator.And,
                    values: getViewRecordingFiltersForVariant(EXPERIMENT, undefined),
                },
            ],
        })
    })

    it('keeps the selected variant across remounts, in step with the playlist persisting its filters', async () => {
        await expectLogic(logic, () => {
            logic.actions.setSelectedVariantKey('test')
        }).toMatchValues({ selectedVariantKey: 'test' })
        logic.unmount()

        const remounted = experimentReplayTabLogic({ experiment: EXPERIMENT })
        remounted.mount()
        expect(remounted.values.selectedVariantKey).toBe('test')
        remounted.unmount()
    })

    it('falls back to "All" when the persisted variant no longer exists', async () => {
        await expectLogic(logic, () => {
            logic.actions.setSelectedVariantKey('test')
        }).toMatchValues({ selectedVariantKey: 'test' })
        logic.unmount()

        // Same experiment id, so the persisted "test" rehydrates — but the variant has since been renamed.
        const renamed = {
            ...EXPERIMENT,
            feature_flag: {
                filters: {
                    multivariate: {
                        variants: [
                            { key: 'control', rollout_percentage: 50 },
                            { key: 'test_v2', rollout_percentage: 50 },
                        ],
                    },
                },
            },
        } as unknown as Experiment
        const remounted = experimentReplayTabLogic({ experiment: renamed })
        remounted.mount()

        expect(remounted.values.selectedVariantKey).toBe('test')
        expect(remounted.values.effectiveVariantKey).toBeNull()
        // The stale key must not leak into the query; the filter falls back to all variants.
        expect(remounted.values.recordingsFilters.filter_group.values).toEqual([
            {
                type: FilterLogicalOperator.And,
                values: getViewRecordingFiltersForVariant(renamed, undefined),
            },
        ])
        remounted.unmount()
    })

    it('narrows the filter to the selected variant, keeping the run window', async () => {
        await expectLogic(logic, () => {
            logic.actions.setSelectedVariantKey('test')
        }).toMatchValues({ selectedVariantKey: 'test' })

        const { recordingsFilters } = logic.values
        expect(recordingsFilters.date_from).toBe('2026-01-01T00:00:00Z')
        expect(recordingsFilters.filter_group.values).toEqual([
            {
                type: FilterLogicalOperator.And,
                values: getViewRecordingFiltersForVariant(EXPERIMENT, 'test'),
            },
        ])
    })

    it('flags a server-side exposure event as unlinkable, so the tab can explain the empty list', async () => {
        seenTogetherSpy.mockResolvedValue({ $feature_flag_called: false })
        // Distinct id: both this logic and the linkability lookup are keyed by experiment id.
        const serverSide = experimentReplayTabLogic({ experiment: { ...EXPERIMENT, id: 43 } as Experiment })
        serverSide.mount()

        await expectLogic(serverSide).toFinishAllListeners().toMatchValues({ exposureUnlinkable: true })
        serverSide.unmount()
    })

    it('keeps the list when the exposure event is session-linkable', async () => {
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ exposureUnlinkable: false })
    })

    it('ANDs each selected metric filter onto the exposure filter, and ignores unknown metric uuids', async () => {
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.metricOptions.map((option) => option.uuid)).toEqual(['metric-purchase', 'metric-funnel'])

        logic.actions.setMetricSelected('metric-purchase', true)
        expect(logic.values.effectiveMetricUuids).toEqual(['metric-purchase'])
        expect(logic.values.recordingsFilters.filter_group.values).toEqual([
            {
                type: FilterLogicalOperator.And,
                values: [
                    ...getViewRecordingFiltersForVariant(EXPERIMENT, undefined),
                    { id: 'purchase', name: 'purchase', type: 'events', properties: [] },
                ],
            },
        ])

        // A second selection narrows further: both metrics' primary events AND together.
        logic.actions.setMetricSelected('metric-funnel', true)
        expect(logic.values.effectiveMetricUuids).toEqual(['metric-purchase', 'metric-funnel'])
        expect(logic.values.recordingsFilters.filter_group.values).toEqual([
            {
                type: FilterLogicalOperator.And,
                values: [
                    ...getViewRecordingFiltersForVariant(EXPERIMENT, undefined),
                    { id: 'purchase', name: 'purchase', type: 'events', properties: [] },
                    { id: 'server_side_step', name: 'server_side_step', type: 'events', properties: [] },
                ],
            },
        ])

        logic.actions.setMetricSelected('metric-purchase', false)
        logic.actions.setMetricSelected('metric-funnel', false)
        // A persisted uuid whose metric has since been removed must not leak into the query.
        logic.actions.setMetricSelected('ghost', true)
        expect(logic.values.effectiveMetricUuids).toEqual([])
        expect(logic.values.recordingsFilters.filter_group.values).toEqual([
            {
                type: FilterLogicalOperator.And,
                values: getViewRecordingFiltersForVariant(EXPERIMENT, undefined),
            },
        ])
    })

    it('lists a retention metric as unmatchable instead of dropping it silently', async () => {
        // A retention metric yields no session filter (its return visit lands in a later session).
        // Dropping it from the list reads as the metric having been forgotten, so it stays listed
        // with a reason — and must never reach the query, which would only narrow to nothing.
        const withRetention = experimentReplayTabLogic({
            experiment: {
                ...EXPERIMENT,
                id: 46,
                metrics_secondary: [
                    ...(EXPERIMENT.metrics_secondary ?? []),
                    {
                        kind: NodeKind.ExperimentMetric,
                        metric_type: ExperimentMetricType.RETENTION,
                        uuid: 'metric-retention',
                        name: '7-day retention',
                        start_event: { kind: NodeKind.EventsNode, event: '$pageview' },
                        completion_event: { kind: NodeKind.EventsNode, event: '$pageview' },
                    },
                ],
            } as unknown as Experiment,
        })
        withRetention.mount()
        await expectLogic(withRetention).toFinishAllListeners()

        expect(withRetention.values.metricOptions.find((option) => option.uuid === 'metric-retention')).toMatchObject({
            name: '7-day retention',
            unlinkable: true,
            unlinkableReason: RETENTION_UNLINKABLE_REASON,
        })
        withRetention.actions.setMetricSelected('metric-retention', true)
        expect(withRetention.values.effectiveMetricUuids).toEqual([])
        expect(withRetention.values.recordingsFilters.filter_group.values).toEqual([
            {
                type: FilterLogicalOperator.And,
                values: getViewRecordingFiltersForVariant(EXPERIMENT, undefined),
            },
        ])
        withRetention.unmount()
    })

    it('disables a fully server-side metric and never ANDs it into the query', async () => {
        seenTogetherSpy.mockResolvedValue({ ...ALL_LINKABLE, purchase: false })
        const serverSideMetric = experimentReplayTabLogic({ experiment: { ...EXPERIMENT, id: 44 } as Experiment })
        serverSideMetric.mount()
        await expectLogic(serverSideMetric).toFinishAllListeners()

        expect(serverSideMetric.values.metricOptions.find((option) => option.uuid === 'metric-purchase')).toMatchObject(
            { unlinkable: true }
        )
        serverSideMetric.actions.setMetricSelected('metric-purchase', true)
        expect(serverSideMetric.values.effectiveMetricUuids).toEqual([])
        // The unlinkable event would zero the whole AND-combined query — it must never appear.
        expect(serverSideMetric.values.recordingsFilters.filter_group.values).toEqual([
            {
                type: FilterLogicalOperator.And,
                values: getViewRecordingFiltersForVariant(EXPERIMENT, undefined),
            },
        ])
        serverSideMetric.unmount()
    })

    it('keeps a partially linkable metric selectable but drops its unlinkable step from the query', async () => {
        seenTogetherSpy.mockResolvedValue({ ...ALL_LINKABLE, server_side_step: false })
        const partiallyLinkable = experimentReplayTabLogic({ experiment: { ...EXPERIMENT, id: 45 } as Experiment })
        partiallyLinkable.mount()
        await expectLogic(partiallyLinkable).toFinishAllListeners()

        expect(partiallyLinkable.values.metricOptions.find((option) => option.uuid === 'metric-funnel')).toMatchObject({
            unlinkable: false,
        })
        partiallyLinkable.actions.setMetricSelected('metric-funnel', true)
        expect(partiallyLinkable.values.recordingsFilters.filter_group.values).toEqual([
            {
                type: FilterLogicalOperator.And,
                values: [
                    ...getViewRecordingFiltersForVariant(EXPERIMENT, undefined),
                    { id: 'client_step', name: 'client_step', type: 'events', properties: [] },
                ],
            },
        ])
        partiallyLinkable.unmount()
    })

    it('filters a multi-source metric on its primary event only, not every source', async () => {
        // Both funnel steps are session-linkable here. The recordings query flattens to a single
        // AND operand, so ANDing every step would demand a session fire *all* of them; we filter on
        // the entry step (series[0]) instead.
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setMetricSelected('metric-funnel', true)
        expect(logic.values.recordingsFilters.filter_group.values).toEqual([
            {
                type: FilterLogicalOperator.And,
                values: [
                    ...getViewRecordingFiltersForVariant(EXPERIMENT, undefined),
                    { id: 'server_side_step', name: 'server_side_step', type: 'events', properties: [] },
                ],
            },
        ])
    })

    it('skips metrics without a uuid — the persisted selection needs a stable identity', async () => {
        // A positional stand-in id would re-attach a persisted selection to a *different* metric
        // once the metric list is edited, silently filtering the playlist on the wrong event.
        const withoutUuid = experimentReplayTabLogic({
            experiment: {
                ...EXPERIMENT,
                id: 47,
                metrics: [{ ...PURCHASE_METRIC, uuid: undefined }],
                metrics_secondary: [],
            } as unknown as Experiment,
        })
        withoutUuid.mount()
        await expectLogic(withoutUuid).toFinishAllListeners()

        expect(withoutUuid.values.metricOptions).toEqual([])
        withoutUuid.unmount()
    })

    it('holds metric filters out of the query until the linkability check lands', async () => {
        // Applying a persisted selection before linkability is known can fire an exposure+metric
        // query that can only be empty (server-side-only metric), flashing a false empty state.
        let resolveSeenTogether!: (map: Record<string, boolean>) => void
        seenTogetherSpy.mockReturnValue(new Promise((resolve) => (resolveSeenTogether = resolve)))
        const pending = experimentReplayTabLogic({ experiment: { ...EXPERIMENT, id: 48 } as Experiment })
        pending.mount()
        pending.actions.setMetricSelected('metric-purchase', true)

        expect(pending.values.recordingsFilters.filter_group.values).toEqual([
            {
                type: FilterLogicalOperator.And,
                values: getViewRecordingFiltersForVariant(EXPERIMENT, undefined),
            },
        ])

        resolveSeenTogether(ALL_LINKABLE)
        await expectLogic(pending).toFinishAllListeners()
        expect(pending.values.recordingsFilters.filter_group.values).toEqual([
            {
                type: FilterLogicalOperator.And,
                values: [
                    ...getViewRecordingFiltersForVariant(EXPERIMENT, undefined),
                    { id: 'purchase', name: 'purchase', type: 'events', properties: [] },
                ],
            },
        ])
        pending.unmount()
    })

    it('applies metric filters when the linkability check fails — fail open, not permanently gated', async () => {
        seenTogetherSpy.mockRejectedValue(new Error('network error'))
        const failed = experimentReplayTabLogic({ experiment: { ...EXPERIMENT, id: 49 } as Experiment })
        failed.mount()
        failed.actions.setMetricSelected('metric-purchase', true)
        await expectLogic(failed).toFinishAllListeners()

        expect(failed.values.recordingsFilters.filter_group.values).toEqual([
            {
                type: FilterLogicalOperator.And,
                values: [
                    ...getViewRecordingFiltersForVariant(EXPERIMENT, undefined),
                    { id: 'purchase', name: 'purchase', type: 'events', properties: [] },
                ],
            },
        ])
        failed.unmount()
    })

    it('prefetches session contexts for a loaded recordings page when the flag is on', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.REPLAY_EXPERIMENT_CONTEXT]: true })
        logic.actions.recordingsLoaded(['s1', 's2'])
        await expectLogic(logic).toFinishAllListeners()

        expect(experimentsSessionContextsCreate).toHaveBeenCalledWith(expect.any(String), {
            session_ids: ['s1', 's2'],
        })
    })

    it('never prefetches for flag-disabled viewers, and caps a batch at the backend limit', async () => {
        // Ungated, every experiment-tab visit would fire the expensive ClickHouse scans for
        // viewers who can't even see the experiments box.
        logic.actions.recordingsLoaded(['s1'])
        await expectLogic(logic).toFinishAllListeners()
        expect(experimentsSessionContextsCreate).not.toHaveBeenCalled()

        // Over-cap ids must be sliced, not sent — the backend 400s the whole batch above its cap.
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.REPLAY_EXPERIMENT_CONTEXT]: true })
        logic.actions.recordingsLoaded(Array.from({ length: 25 }, (_, index) => `session-${index}`))
        await expectLogic(logic).toFinishAllListeners()
        expect(experimentsSessionContextsCreate).toHaveBeenCalledTimes(1)
        expect((experimentsSessionContextsCreate as jest.Mock).mock.calls[0][1].session_ids).toHaveLength(20)
    })

    it('offers saved/shared metrics in the facet, deduped by uuid', async () => {
        const savedMetric = {
            query: {
                kind: NodeKind.ExperimentMetric,
                metric_type: ExperimentMetricType.MEAN,
                uuid: 'metric-saved',
                name: 'Signups',
                source: { kind: NodeKind.EventsNode, event: 'signup' },
            },
        }
        const withSaved = experimentReplayTabLogic({
            experiment: {
                ...EXPERIMENT,
                id: 46,
                // Same saved metric linked twice (e.g. primary + secondary) must yield one chip.
                saved_metrics: [savedMetric, savedMetric],
            } as unknown as Experiment,
        })
        withSaved.mount()
        await expectLogic(withSaved).toFinishAllListeners()

        expect(withSaved.values.metricOptions.map((option) => option.uuid)).toEqual([
            'metric-purchase',
            'metric-funnel',
            'metric-saved',
        ])
        withSaved.unmount()
    })
})
