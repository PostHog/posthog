import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { aiGatewayLogic } from './aiGatewayLogic'
import { gatewaysList, gatewaysPartialUpdate } from './generated/api'

jest.mock('./generated/api', () => ({
    gatewaysList: jest.fn(),
    gatewaysPartialUpdate: jest.fn(),
}))

jest.mock('./gatewayUsage', () => ({
    fetchGatewayUsage: jest.fn().mockResolvedValue({ requests: 0, inputTokens: 0, outputTokens: 0, costUsd: 0 }),
}))

const mockList = gatewaysList as jest.MockedFunction<typeof gatewaysList>
const mockUpdate = gatewaysPartialUpdate as jest.MockedFunction<typeof gatewaysPartialUpdate>

const gateway = (id: string, slug: string): any => ({
    id,
    slug,
    created_at: '',
    updated_at: null,
    created_by: {},
})

describe('aiGatewayLogic', () => {
    let logic: ReturnType<typeof aiGatewayLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        mockList.mockResolvedValue({ results: [gateway('g1', 'default')] } as any)
        initKeaTests()
        logic = aiGatewayLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('loads gateways on mount', async () => {
        await expectLogic(logic).toDispatchActions(['loadGatewaysSuccess'])
        expect(logic.values.gateways).toEqual([gateway('g1', 'default')])
    })

    it('rejects an empty slug without making a request', async () => {
        logic.actions.openEditGateway(gateway('g1', 'default'))
        logic.actions.setEditingGatewayValue('slug', '')
        await expectLogic(logic, () => logic.actions.submitEditingGateway()).toFinishAllListeners()
        expect(mockUpdate).not.toHaveBeenCalled()
    })

    it('rejects a malformed slug without making a request', async () => {
        logic.actions.openEditGateway(gateway('g1', 'default'))
        logic.actions.setEditingGatewayValue('slug', 'Not Valid')
        await expectLogic(logic, () => logic.actions.submitEditingGateway()).toFinishAllListeners()
        expect(mockUpdate).not.toHaveBeenCalled()
    })

    it('renames a gateway via partial update and closes the modal', async () => {
        mockUpdate.mockResolvedValue(gateway('g1', 'renamed'))
        logic.actions.openEditGateway(gateway('g1', 'default'))
        logic.actions.setEditingGatewayValue('slug', 'renamed')
        await expectLogic(logic, () => logic.actions.submitEditingGateway()).toFinishAllListeners()
        expect(mockUpdate).toHaveBeenCalledWith(expect.any(String), 'g1', { slug: 'renamed' })
        expect(logic.values.editingGatewayId).toBeNull()
    })
})
