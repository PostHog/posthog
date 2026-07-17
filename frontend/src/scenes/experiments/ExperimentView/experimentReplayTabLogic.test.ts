import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'
import { Experiment, FilterLogicalOperator } from '~/types'

import { getViewRecordingFiltersForVariant } from '../utils'
import { experimentReplayTabLogic } from './experimentReplayTabLogic'

jest.mock('lib/utils/product-intents', () => ({
    addProductIntentForCrossSell: jest.fn().mockResolvedValue(null),
}))

const EXPERIMENT = {
    id: 42,
    feature_flag_key: 'my-flag',
    start_date: '2026-01-01T00:00:00Z',
    end_date: '2026-02-01T00:00:00Z',
    exposure_criteria: { filterTestAccounts: true },
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

describe('experimentReplayTabLogic', () => {
    let logic: ReturnType<typeof experimentReplayTabLogic.build>
    let seenTogetherSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        seenTogetherSpy = jest.spyOn(api.propertyDefinitions, 'seenTogether')
        seenTogetherSpy.mockResolvedValue({ $feature_flag_called: true })
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
})
