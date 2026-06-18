import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { aiGatewayLogic } from './aiGatewayLogic'
import { fetchGatewayUsage, fetchGatewayUsageByModel } from './gatewayUsage'

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({ lemonToast: { info: jest.fn() } }))

jest.mock('./gatewayUsage', () => ({
    fetchGatewayUsage: jest.fn().mockResolvedValue({ requests: 12, inputTokens: 100, outputTokens: 200, costUsd: 3.5 }),
    fetchGatewaySpendByDay: jest.fn().mockResolvedValue([{ day: '2024-07-01', costUsd: 1.5 }]),
    fetchGatewayUsageByModel: jest
        .fn()
        .mockResolvedValue([{ model: 'gpt-5-mini', requests: 12, tokens: 300, costUsd: 3.5 }]),
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

    it('loads usage, spend series, and model usage on mount', async () => {
        logic.mount()
        await expectLogic(logic).toDispatchActions([
            'loadUsageSuccess',
            'loadSpendSeriesSuccess',
            'loadModelUsageSuccess',
        ])
        expect(logic.values.usage).toEqual({ requests: 12, inputTokens: 100, outputTokens: 200, costUsd: 3.5 })
        expect(logic.values.modelUsage).toEqual([{ model: 'gpt-5-mini', requests: 12, tokens: 300, costUsd: 3.5 }])
        expect(logic.values.hasUsage).toBe(true)
    })

    it('reports no usage for a team that has never called the gateway', async () => {
        jest.mocked(fetchGatewayUsage).mockResolvedValueOnce({
            requests: 0,
            inputTokens: 0,
            outputTokens: 0,
            costUsd: 0,
        })
        jest.mocked(fetchGatewayUsageByModel).mockResolvedValueOnce([])

        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadUsageSuccess', 'loadModelUsageSuccess'])
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
