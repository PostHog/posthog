import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { aiGatewayDetailLogic } from './aiGatewayDetailLogic'
import { gatewaysCredentialsRetrieve, gatewaysList, gatewaysRetrieve } from './generated/api'

jest.mock('./generated/api', () => ({
    gatewaysRetrieve: jest.fn(),
    gatewaysList: jest.fn(),
    gatewaysCredentialsRetrieve: jest.fn(),
    gatewaysCreate: jest.fn(),
    gatewaysPartialUpdate: jest.fn(),
    gatewaysDestroy: jest.fn(),
    gatewaysBindCredentialCreate: jest.fn(),
}))

const mockRetrieve = gatewaysRetrieve as jest.MockedFunction<typeof gatewaysRetrieve>
const mockList = gatewaysList as jest.MockedFunction<typeof gatewaysList>
const mockCredentials = gatewaysCredentialsRetrieve as jest.MockedFunction<typeof gatewaysCredentialsRetrieve>

describe('aiGatewayDetailLogic', () => {
    let logic: ReturnType<typeof aiGatewayDetailLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        mockRetrieve.mockResolvedValue({ id: 'g1', slug: 'default' } as any)
        mockList.mockResolvedValue({ results: [] } as any)
        mockCredentials.mockResolvedValue({ personal_api_keys: [], oauth_applications: [] } as any)
        jest.spyOn(api, 'query').mockResolvedValue({ results: [[10, 100, 200, 1.5]] } as any)
        initKeaTests()
        logic = aiGatewayDetailLogic({ id: 'g1' })
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('loads the gateway then its usage on mount', async () => {
        await expectLogic(logic).toDispatchActions(['loadGatewaySuccess', 'loadUsageSuccess'])
        expect(mockRetrieve).toHaveBeenCalledWith(expect.any(String), 'g1')
        expect(logic.values.gateway?.slug).toEqual('default')
        expect(logic.values.usage).toEqual({ requests: 10, inputTokens: 100, outputTokens: 200, costUsd: 1.5 })
    })

    it('filters the usage query by the gateway slug', async () => {
        await expectLogic(logic).toDispatchActions(['loadUsageSuccess'])
        const slugCall = (api.query as jest.Mock).mock.calls.find((c) => c[0]?.values?.slug === 'default')
        expect(slugCall).not.toBeUndefined()
        expect(slugCall![0].query).toContain('$ai_gateway_slug')
    })
})
