import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { aiGatewayLogic } from './aiGatewayLogic'

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
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('loads usage, spend series, and model usage on mount', async () => {
        await expectLogic(logic).toDispatchActions([
            'loadUsageSuccess',
            'loadSpendSeriesSuccess',
            'loadModelUsageSuccess',
        ])
        expect(logic.values.usage).toEqual({ requests: 12, inputTokens: 100, outputTokens: 200, costUsd: 3.5 })
        expect(logic.values.modelUsage).toEqual([{ model: 'gpt-5-mini', requests: 12, tokens: 300, costUsd: 3.5 }])
    })

    it('confirming a top up closes the modal', async () => {
        await expectLogic(logic, () => {
            logic.actions.setTopUpAmount(100)
            logic.actions.openTopUpModal()
        }).toMatchValues({ isTopUpModalOpen: true, topUpAmountUsd: 100 })

        await expectLogic(logic, () => logic.actions.confirmTopUp()).toMatchValues({ isTopUpModalOpen: false })
    })
})
