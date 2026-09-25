import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import posthog from 'lib/posthog-typed'
import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'
import { AvailableFeature, InsightLogicProps, UserType } from '~/types'

import { subscriptionsList } from 'products/subscriptions/frontend/generated/api'

import { INSIGHT_SUBSCRIBE_NUDGE_VIEW_THRESHOLD, insightSubscribeNudgeLogic } from './insightSubscribeNudgeLogic'

jest.mock('lib/posthog-typed', () => ({ __esModule: true, default: { capture: jest.fn() } }))
jest.mock('products/subscriptions/frontend/generated/api', () => ({ subscriptionsList: jest.fn() }))
jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({ lemonToast: { info: jest.fn() } }))

const mockSubscriptionsList = subscriptionsList as jest.Mock
const props = {
    insightId: 1,
    insightShortId: 'test-insight',
    insightName: 'Key metric',
    canEditInsight: true,
    insightProps: { dashboardItemId: 'test-insight' } as InsightLogicProps,
}

const userWithSubscriptions: UserType = {
    ...MOCK_DEFAULT_USER,
    organization: {
        ...MOCK_DEFAULT_ORGANIZATION,
        available_product_features: [{ key: AvailableFeature.SUBSCRIPTIONS, name: 'Subscriptions' }],
    },
}

describe('insightSubscribeNudgeLogic', () => {
    let now = 1_700_000_000_000
    let dateSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        window.localStorage.clear()
        jest.clearAllMocks()
        dateSpy = jest.spyOn(Date, 'now').mockImplementation(() => now)
        mockSubscriptionsList.mockResolvedValue({ count: 0, results: [] })
        userLogic.mount()
        userLogic.actions.loadUserSuccess(userWithSubscriptions)
    })

    afterEach(() => dateSpy.mockRestore())

    it('shows a nudge after three distinct views of an unsubscribed insight', async () => {
        const logic = insightSubscribeNudgeLogic(props)
        logic.mount()

        for (let view = 0; view < INSIGHT_SUBSCRIBE_NUDGE_VIEW_THRESHOLD; view++) {
            logic.actions.recordInsightView(props.insightId)
            now += 61_000
        }

        await expectLogic(logic).toFinishAllListeners()

        expect(mockSubscriptionsList).toHaveBeenCalledWith(expect.any(String), { insight: props.insightId, limit: 1 })
        expect(posthog.capture).toHaveBeenCalledWith('insight subscribe nudge shown', {
            insight_id: props.insightId,
            view_count_7d: INSIGHT_SUBSCRIBE_NUDGE_VIEW_THRESHOLD,
        })
        logic.unmount()
    })
})
