import { ApiError } from 'lib/api-error'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import { dataModelingNodesAttentionCountRetrieve } from 'products/data_modeling/frontend/generated/api'
import { dataQualityChecksFailingCountRetrieve } from 'products/data_quality/frontend/generated/api'

import { dataCatalogAttentionLogic } from './dataCatalogAttentionLogic'
import { dataCatalogPendingReviewRetrieve } from './generated/api'

jest.mock('lib/api', () => ({
    __esModule: true,
    default: {},
    ApiConfig: { getCurrentTeamId: jest.fn(() => 1) },
}))
jest.mock('./generated/api', () => ({ dataCatalogPendingReviewRetrieve: jest.fn() }))
jest.mock('products/data_modeling/frontend/generated/api', () => ({
    dataModelingNodesAttentionCountRetrieve: jest.fn(),
}))
jest.mock('products/data_quality/frontend/generated/api', () => ({ dataQualityChecksFailingCountRetrieve: jest.fn() }))

const RESTRUCTURE_FLAGS = { [FEATURE_FLAGS.TODAY_RAIL_NAV]: true, [FEATURE_FLAGS.DATA_CATALOG_RESTRUCTURE]: true }

describe('dataCatalogAttentionLogic', () => {
    let logic: ReturnType<typeof dataCatalogAttentionLogic.build>

    function mountWithFlags(flags: Record<string, boolean>): void {
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags(Object.keys(flags), flags)
        logic = dataCatalogAttentionLogic()
        logic.mount()
    }

    beforeEach(() => {
        jest.clearAllMocks()
        ;(dataCatalogPendingReviewRetrieve as jest.Mock).mockResolvedValue({
            metrics: 3,
            relationships: 0,
            certifications: 1,
        })
        ;(dataModelingNodesAttentionCountRetrieve as jest.Mock).mockResolvedValue({ count: 4 })
        ;(dataQualityChecksFailingCountRetrieve as jest.Mock).mockResolvedValue({ count: 2 })
    })

    afterEach(() => {
        logic.unmount()
    })

    it('fetches nothing while the new catalog is off', async () => {
        mountWithFlags({})

        logic.actions.loadAttention()
        await expectLogic(logic).toDispatchActions(['loadAttentionSuccess'])

        expect(dataCatalogPendingReviewRetrieve).not.toHaveBeenCalled()
        expect(logic.values.totalCount).toEqual(0)
    })

    it('counts each tab', async () => {
        mountWithFlags(RESTRUCTURE_FLAGS)

        logic.actions.loadAttention()
        await expectLogic(logic).toDispatchActions(['loadAttentionSuccess'])

        expect(logic.values.tabCounts).toEqual({
            overview: 4,
            tables: 1,
            metrics: 3,
            relationships: 0,
            'data-quality': 2,
        })
        expect(logic.values.totalCount).toEqual(10)
        expect(logic.values.hasFailures).toBe(true)
    })

    it.each([
        ['access denied clears the count', new ApiError('Forbidden', 403), 0],
        ['a server error keeps the last count', new ApiError('Server error', 500), 4],
        ['a timeout keeps the last count', new DOMException('The operation timed out.', 'TimeoutError'), 4],
    ])('on refresh, %s', async (_case, failure, expectedFailingModels) => {
        mountWithFlags(RESTRUCTURE_FLAGS)
        logic.actions.loadAttention()
        await expectLogic(logic).toDispatchActions(['loadAttentionSuccess'])
        ;(dataModelingNodesAttentionCountRetrieve as jest.Mock).mockRejectedValue(failure)

        logic.actions.loadAttention()
        await expectLogic(logic).toDispatchActions(['loadAttentionSuccess'])

        expect(logic.values.attention.failingModels).toEqual(expectedFailingModels)
        expect(logic.values.attention.failingChecks).toEqual(2)
    })
})
