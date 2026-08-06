import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { aiGatewayLogic } from './aiGatewayLogic'
import { fetchGatewayUsageByModel } from './gatewayUsage'

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({ lemonToast: { info: jest.fn(), error: jest.fn() } }))

jest.mock('./gatewayUsage', () => ({
    fetchGatewaySpendByDay: jest.fn().mockResolvedValue([{ day: '2024-07-01', costUsd: 1.5 }]),
    fetchGatewayUsageByModel: jest
        .fn()
        .mockResolvedValue([{ model: 'gpt-5-mini', requests: 12, inputTokens: 100, outputTokens: 200, costUsd: 3.5 }]),
    buildSpendChartData: jest.fn().mockReturnValue({ data: [], labels: [] }),
}))

describe('aiGatewayLogic', () => {
    let logic: ReturnType<typeof aiGatewayLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        logic = aiGatewayLogic()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('loads spend series and model usage on mount, deriving usage totals from the breakdown', async () => {
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadSpendSeriesSuccess', 'loadModelUsageSuccess'])
        expect(logic.values.usage).toEqual({ requests: 12, inputTokens: 100, outputTokens: 200, costUsd: 3.5 })
        expect(logic.values.modelUsage).toEqual([
            { model: 'gpt-5-mini', requests: 12, inputTokens: 100, outputTokens: 200, costUsd: 3.5 },
        ])
        expect(logic.values.hasUsage).toBe(true)
    })

    it('reports no usage for a team that has never called the gateway', async () => {
        jest.mocked(fetchGatewayUsageByModel).mockResolvedValueOnce([])

        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadModelUsageSuccess'])
        expect(logic.values.hasUsage).toBe(false)
    })

    it('confirming a top up closes the modal', async () => {
        logic.mount()
        await expectLogic(logic, () => {
            logic.actions.setTopUpAmount(100)
            logic.actions.openTopUpModal()
        }).toMatchValues({ isTopUpModalOpen: true, topUpAmountUsd: 100 })

        await expectLogic(logic, () => logic.actions.confirmTopUp()).toMatchValues({ isTopUpModalOpen: false })
    })
})
