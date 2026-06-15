import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { aiGatewayLogic } from './aiGatewayLogic'

jest.mock('./gatewayUsage', () => ({
    fetchGatewayUsage: jest.fn().mockResolvedValue({ requests: 12, inputTokens: 100, outputTokens: 200, costUsd: 3.5 }),
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

    it('loads project-wide usage on mount', async () => {
        await expectLogic(logic).toDispatchActions(['loadUsageSuccess'])
        expect(logic.values.usage).toEqual({ requests: 12, inputTokens: 100, outputTokens: 200, costUsd: 3.5 })
    })
})
