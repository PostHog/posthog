import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { Experiment, FilterLogicalOperator } from '~/types'

import { getViewRecordingFiltersForVariant } from '../utils'
import { experimentReplayTabLogic } from './experimentReplayTabLogic'

jest.mock('lib/utils/product-intents', () => ({
    addProductIntentForCrossSell: jest.fn().mockResolvedValue(null),
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

    it('ANDs the selected metric filter onto the exposure filter, and ignores unknown metric uuids', async () => {
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.metricOptions.map((option) => option.uuid)).toEqual(['metric-purchase', 'metric-funnel'])

        logic.actions.setSelectedMetricUuid('metric-purchase')
        expect(logic.values.effectiveMetricUuid).toBe('metric-purchase')
        expect(logic.values.recordingsFilters.filter_group.values).toEqual([
            {
                type: FilterLogicalOperator.And,
                values: [
                    ...getViewRecordingFiltersForVariant(EXPERIMENT, undefined),
                    { id: 'purchase', name: 'purchase', type: 'events', properties: [] },
                ],
            },
        ])

        // A persisted uuid whose metric has since been removed must not leak into the query.
        logic.actions.setSelectedMetricUuid('ghost')
        expect(logic.values.effectiveMetricUuid).toBeNull()
        expect(logic.values.recordingsFilters.filter_group.values).toEqual([
            {
                type: FilterLogicalOperator.And,
                values: getViewRecordingFiltersForVariant(EXPERIMENT, undefined),
            },
        ])
    })

    it('disables a fully server-side metric and never ANDs it into the query', async () => {
        seenTogetherSpy.mockResolvedValue({ ...ALL_LINKABLE, purchase: false })
        const serverSideMetric = experimentReplayTabLogic({ experiment: { ...EXPERIMENT, id: 44 } as Experiment })
        serverSideMetric.mount()
        await expectLogic(serverSideMetric).toFinishAllListeners()

        expect(serverSideMetric.values.metricOptions.find((option) => option.uuid === 'metric-purchase')).toMatchObject(
            { unlinkable: true }
        )
        serverSideMetric.actions.setSelectedMetricUuid('metric-purchase')
        expect(serverSideMetric.values.effectiveMetricUuid).toBeNull()
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
        partiallyLinkable.actions.setSelectedMetricUuid('metric-funnel')
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
})
