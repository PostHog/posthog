import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { playerSidebarLogic } from 'scenes/session-recordings/player/sidebar/playerSidebarLogic'

import { ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import {
    Experiment,
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    SessionRecordingSidebarTab,
} from '~/types'

import {
    experimentsSessionBucketsCreate,
    experimentsSessionContextsCreate,
} from 'products/experiments/frontend/generated/api'

import {
    FUNNEL_DATA_WAREHOUSE_COMPLETION_REASON,
    FUNNEL_SERVER_SIDE_COMPLETION_REASON,
    getViewRecordingFiltersForVariant,
} from '../utils'
import { RETENTION_UNLINKABLE_REASON } from '../viewRecordingsLinkabilityLogic'
import { experimentReplayTabLogic } from './experimentReplayTabLogic'

jest.mock('lib/utils/product-intents', () => ({
    addProductIntentForCrossSell: jest.fn().mockResolvedValue(null),
}))

jest.mock('products/experiments/frontend/generated/api', () => ({
    experimentsSessionContextsCreate: jest.fn().mockResolvedValue({ results: [] }),
    experimentsSessionBucketsCreate: jest.fn(),
}))

const BUCKET_RESPONSE = {
    session_ids: ['bucket-1', 'bucket-2'],
    truncated: false,
    considered_metrics: [{ metric_uuid: 'metric-purchase', metric_name: 'Purchase' }],
    excluded_metrics: [],
    date_from: '2026-01-01T00:00:00Z',
    date_to: '2026-02-01T00:00:00Z',
    filter_test_accounts: true,
}

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
        ;(experimentsSessionBucketsCreate as jest.Mock).mockClear()
        ;(experimentsSessionBucketsCreate as jest.Mock).mockResolvedValue(BUCKET_RESPONSE)
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

    it('falls back to the flag-value property filter when the default exposure event is server-side', async () => {
        seenTogetherSpy.mockResolvedValue({ $feature_flag_called: false })
        // Distinct id: both this logic and the linkability lookup are keyed by experiment id.
        const serverSide = experimentReplayTabLogic({ experiment: { ...EXPERIMENT, id: 43 } as Experiment })
        serverSide.mount()

        await expectLogic(serverSide)
            .toFinishAllListeners()
            .toMatchValues({ exposureUnlinkable: false, usingExposureFallback: true })
        expect(serverSide.values.recordingsFilters.filter_group.values).toEqual([
            {
                type: FilterLogicalOperator.And,
                values: [
                    {
                        key: '$feature/my-flag',
                        type: PropertyFilterType.Event,
                        value: ['control', 'test'],
                        operator: PropertyOperator.Exact,
                    },
                ],
            },
        ])
        serverSide.unmount()
    })

    it('flags a server-side custom exposure event as unlinkable, so the tab can explain the empty list', async () => {
        seenTogetherSpy.mockResolvedValue({ signed_up: false })
        const customExposure = {
            ...EXPERIMENT,
            id: 44,
            exposure_criteria: {
                exposure_config: { kind: NodeKind.ExperimentEventExposureConfig, event: 'signed_up', properties: [] },
            },
        } as unknown as Experiment
        const serverSide = experimentReplayTabLogic({ experiment: customExposure })
        serverSide.mount()

        await expectLogic(serverSide)
            .toFinishAllListeners()
            .toMatchValues({ exposureUnlinkable: true, usingExposureFallback: false })
        serverSide.unmount()
    })

    it('keeps the list when the exposure event is session-linkable', async () => {
        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({ exposureUnlinkable: false, usingExposureFallback: false })
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
        await expectLogic(partiallyLinkable).toFinishAllListeners()
        // A multi-source metric resolves server-side, where the unmatchable step is simply one
        // OR arm that never matches a session — so it drops out without narrowing anything.
        expect(experimentsSessionBucketsCreate).toHaveBeenLastCalledWith(expect.any(String), 45, {
            bucket: 'fired_any',
            metric_uuids: ['metric-funnel'],
            variant: null,
        })
        expect(partiallyLinkable.values.recordingsFilters.session_ids).toEqual(['bucket-1', 'bucket-2'])
        partiallyLinkable.unmount()
    })

    it('resolves one multi-source metric server-side, and one single-source metric client-side', async () => {
        await expectLogic(logic).toFinishAllListeners()

        // A single event is expressible as a filter: exact, uncapped, no request.
        logic.actions.setMetricSelected('metric-purchase', true)
        await expectLogic(logic).toFinishAllListeners()
        expect(experimentsSessionBucketsCreate).not.toHaveBeenCalled()
        expect(logic.values.recordingsFilters.session_ids).toBeUndefined()
        expect(logic.values.recordingsFilters.filter_group.values).toEqual([
            {
                type: FilterLogicalOperator.And,
                values: [
                    ...getViewRecordingFiltersForVariant(EXPERIMENT, undefined),
                    { id: 'purchase', name: 'purchase', type: 'events', properties: [] },
                ],
            },
        ])

        // Several events are not: a recordings query carries one operator for its whole tree, so
        // the filter could only match the metric's first event and would silently miss the rest.
        logic.actions.setMetricSelected('metric-purchase', false)
        logic.actions.setMetricSelected('metric-funnel', true)
        await expectLogic(logic).toFinishAllListeners()
        expect(experimentsSessionBucketsCreate).toHaveBeenLastCalledWith(expect.any(String), 42, {
            bucket: 'fired_any',
            metric_uuids: ['metric-funnel'],
            variant: null,
        })
        expect(logic.values.recordingsFilters.session_ids).toEqual(['bucket-1', 'bucket-2'])
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

    it('re-warms the rest of the page when a recording is opened', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.REPLAY_EXPERIMENT_CONTEXT]: true })

        // Opening before any page has loaded must not fire an empty batch (the backend 400s it).
        logic.actions.recordingOpened('s1')
        await expectLogic(logic).toFinishAllListeners()
        expect(experimentsSessionContextsCreate).not.toHaveBeenCalled()

        logic.actions.recordingsLoaded(['s1', 's2', 's3'])
        await expectLogic(logic).toFinishAllListeners()

        // The server-side cache TTL runs from prefetch time, so each open must re-warm the
        // page — without this, a user who watches one recording past the TTL opens every
        // later one cold. The opened id is excluded: the player is fetching it right now.
        logic.actions.recordingOpened('s2')
        await expectLogic(logic).toFinishAllListeners()

        expect(experimentsSessionContextsCreate).toHaveBeenCalledTimes(2)
        expect((experimentsSessionContextsCreate as jest.Mock).mock.calls[1][1].session_ids).toEqual(['s1', 's3'])
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
    it('hands the list to the bucket endpoint for filters the recordings query cannot express', async () => {
        await expectLogic(logic, () => {
            logic.actions.setSelectedVariantKey('test')
            logic.actions.setMetricSelected('metric-purchase', true)
            logic.actions.setMetricSelected('metric-funnel', true)
            logic.actions.setMetricFilterMode('fired_any')
        }).toFinishAllListeners()

        expect(experimentsSessionBucketsCreate).toHaveBeenLastCalledWith(expect.any(String), 42, {
            bucket: 'fired_any',
            metric_uuids: ['metric-purchase', 'metric-funnel'],
            variant: 'test',
        })
        const { recordingsFilters } = logic.values
        expect(recordingsFilters.session_ids).toEqual(['bucket-1', 'bucket-2'])
        // The returned set already encodes the metric condition; ANDing the event filters back in
        // would narrow it a second time.
        expect(recordingsFilters.filter_group.values).toEqual([
            {
                type: FilterLogicalOperator.And,
                values: getViewRecordingFiltersForVariant(EXPERIMENT, 'test'),
            },
        ])
    })

    it('follows the playlist\'s own "Show all" back to the unbucketed list', async () => {
        await expectLogic(logic, () => {
            logic.actions.setMetricFilterMode('no_metric_activity')
        }).toFinishAllListeners()
        expect(logic.values.recordingsFilters.session_ids).toEqual(['bucket-1', 'bucket-2'])

        // The shared playlist clears session_ids itself; without following it the tab would push
        // the same ids straight back and the control would look broken.
        await expectLogic(logic, () => {
            logic.actions.playlistFiltersChanged({ ...logic.values.recordingsFilters, session_ids: undefined })
        }).toMatchValues({ metricFilterMode: 'fired_all' })
        expect(logic.values.recordingsFilters.session_ids).toBeUndefined()
    })

    it('takes one funnel metric for drop-off and leaves the rest unselectable', async () => {
        await expectLogic(logic, () => {
            logic.actions.setMetricSelected('metric-purchase', true)
            logic.actions.setMetricSelected('metric-funnel', true)
            logic.actions.setMetricFilterMode('funnel_dropoff')
        }).toFinishAllListeners()

        // A mean metric isn't a funnel, and drop-off takes exactly one funnel at a time.
        expect(logic.values.effectiveMetricUuids).toEqual(['metric-funnel'])
        expect(experimentsSessionBucketsCreate).toHaveBeenLastCalledWith(expect.any(String), 42, {
            bucket: 'funnel_dropoff',
            metric_uuids: ['metric-funnel'],
            variant: null,
        })
    })

    it.each([
        [
            'server-side',
            [
                { kind: NodeKind.EventsNode, event: 'client_step' },
                { kind: NodeKind.EventsNode, event: 'server_side_step' },
            ],
            FUNNEL_SERVER_SIDE_COMPLETION_REASON,
        ],
        [
            'data warehouse',
            [
                { kind: NodeKind.EventsNode, event: 'client_step' },
                { kind: NodeKind.EventsNode, event: 'purchase' },
                { kind: NodeKind.ExperimentDataWarehouseNode, table_name: 'stripe_charges' },
            ],
            FUNNEL_DATA_WAREHOUSE_COMPLETION_REASON,
        ],
    ])('refuses drop-off when the funnel finishes on a %s step', async (_name, series, expectedReason) => {
        seenTogetherSpy.mockResolvedValue({ ...ALL_LINKABLE, server_side_step: false })
        const unmatchableFinish = experimentReplayTabLogic({
            experiment: {
                ...EXPERIMENT,
                id: 50,
                metrics_secondary: [{ ...FUNNEL_METRIC, series }],
            } as unknown as Experiment,
        })
        unmatchableFinish.mount()

        await expectLogic(unmatchableFinish, () => {
            unmatchableFinish.actions.setMetricSelected('metric-funnel', true)
            unmatchableFinish.actions.setMetricFilterMode('funnel_dropoff')
        }).toFinishAllListeners()

        // The other steps stay matchable, so the metric is selectable in every other mode.
        // Drop-off is the one that reads the last step, and a completion no recording can show
        // would return every exposed session as not having finished.
        expect(unmatchableFinish.values.metricOptions.find((option) => option.uuid === 'metric-funnel')).toMatchObject({
            unlinkable: false,
            dropoffReason: expectedReason,
        })
        expect(unmatchableFinish.values.effectiveMetricUuids).toEqual([])
        // Nothing is asked of the endpoint, which would refuse this funnel anyway.
        expect(unmatchableFinish.values.sessionBucketRequest).toBeNull()
        expect(unmatchableFinish.values.recordingsFilters.session_ids).toBeUndefined()
        unmatchableFinish.unmount()
    })

    it('asks the endpoint for drop-off on a single-step funnel', async () => {
        const oneStepFunnel = experimentReplayTabLogic({
            experiment: {
                ...EXPERIMENT,
                id: 51,
                metrics_secondary: [
                    { ...FUNNEL_METRIC, series: [{ kind: NodeKind.EventsNode, event: 'client_step' }] },
                ],
            } as unknown as Experiment,
        })
        oneStepFunnel.mount()

        await expectLogic(oneStepFunnel, () => {
            oneStepFunnel.actions.setMetricSelected('metric-funnel', true)
            oneStepFunnel.actions.setMetricFilterMode('funnel_dropoff')
        }).toFinishAllListeners()

        // The funnel's first step is the exposure, so one series step is a complete funnel. A
        // single-event metric must not fall back to the client-side filter path other modes use.
        expect(oneStepFunnel.values.metricOptions.find((option) => option.uuid === 'metric-funnel')).toMatchObject({
            dropoffReason: null,
        })
        expect(experimentsSessionBucketsCreate).toHaveBeenLastCalledWith(expect.any(String), 51, {
            bucket: 'funnel_dropoff',
            metric_uuids: ['metric-funnel'],
            variant: null,
        })
        oneStepFunnel.unmount()
    })

    it('keeps the list empty when the bucket fails, rather than widening it silently', async () => {
        ;(experimentsSessionBucketsCreate as jest.Mock).mockRejectedValue(new Error('boom'))

        await expectLogic(logic, () => {
            logic.actions.setMetricSelected('metric-purchase', true)
            logic.actions.setMetricSelected('metric-funnel', true)
            logic.actions.setMetricFilterMode('fired_any')
        }).toFinishAllListeners()

        // Falling back to no session_ids would show every exposed session under a label that
        // promises a narrower set. The message is kept, not just a flag: a rejected request
        // usually says what to fix.
        expect(logic.values.sessionBucketError).toBe('boom')
        expect(logic.values.recordingsFilters.session_ids).toEqual([])
    })

    it('keeps a picked mode that has nothing to filter on yet', async () => {
        // The tab pushes no session_ids until an eligible metric is picked, and the playlist echoes
        // that back through onFiltersChange. Reading it as the user clearing the bucket bounced the
        // mode straight back to "Fired all" the moment it was picked.
        const oneStepFunnel = experimentReplayTabLogic({
            experiment: {
                ...EXPERIMENT,
                id: 47,
                metrics_secondary: [{ ...FUNNEL_METRIC, series: [FUNNEL_METRIC.series[0]] }],
            } as unknown as Experiment,
        })
        oneStepFunnel.mount()

        await expectLogic(oneStepFunnel, () => {
            oneStepFunnel.actions.setMetricFilterMode('funnel_dropoff')
        }).toFinishAllListeners()
        oneStepFunnel.actions.playlistFiltersChanged(oneStepFunnel.values.recordingsFilters)

        expect(oneStepFunnel.values.metricFilterMode).toBe('funnel_dropoff')
        // No funnel with two matchable steps, so nothing is asked of the endpoint either.
        expect(oneStepFunnel.values.sessionBucketRequest).toBeNull()
        expect(experimentsSessionBucketsCreate).not.toHaveBeenCalled()
        oneStepFunnel.unmount()
    })
    it("lists metrics in the experiment page's order, and never hides one missing from it", async () => {
        // The ordering arrays are the metrics page's display order. Sorting on them keeps the two
        // surfaces in step; filtering on them would silently drop a metric whose uuid never made
        // it into the array (older experiments, or a row written outside the API).
        const ordered = experimentReplayTabLogic({
            experiment: {
                ...EXPERIMENT,
                id: 48,
                metrics: [PURCHASE_METRIC, FUNNEL_METRIC],
                metrics_secondary: [],
                primary_metrics_ordered_uuids: ['metric-funnel'],
            } as unknown as Experiment,
        })
        ordered.mount()
        await expectLogic(ordered).toFinishAllListeners()

        expect(ordered.values.metricOptions.map((option) => option.uuid)).toEqual(['metric-funnel', 'metric-purchase'])
        ordered.unmount()
    })

    it('lands the player sidebar on Overview, and hands it back when the tab goes away', () => {
        // Held mounted across the unmount below, standing in for a player that outlives this tab —
        // the only case in which the reset has anything to do.
        const sidebar = playerSidebarLogic()
        sidebar.mount()

        // Recordings are opened from here to see what the experiment did to a session, which is what
        // the Overview tab shows. Landing on Inspector instead hides it behind a click.
        expect(sidebar.values.defaultTab).toBe(SessionRecordingSidebarTab.OVERVIEW)

        logic.unmount()
        expect(sidebar.values.defaultTab).toBe(SessionRecordingSidebarTab.INSPECTOR)

        sidebar.unmount()
    })
})
