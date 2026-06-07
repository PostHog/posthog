import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { aiGatewayLogic } from './aiGatewayLogic'
import { gatewaysCreate, gatewaysDestroy, gatewaysList, gatewaysPartialUpdate } from './generated/api'

jest.mock('./generated/api', () => ({
    gatewaysList: jest.fn(),
    gatewaysCreate: jest.fn(),
    gatewaysPartialUpdate: jest.fn(),
    gatewaysDestroy: jest.fn(),
}))

const mockList = gatewaysList as jest.MockedFunction<typeof gatewaysList>
const mockCreate = gatewaysCreate as jest.MockedFunction<typeof gatewaysCreate>
const mockUpdate = gatewaysPartialUpdate as jest.MockedFunction<typeof gatewaysPartialUpdate>
const mockDestroy = gatewaysDestroy as jest.MockedFunction<typeof gatewaysDestroy>

const gateway = (id: string, slug: string): any => ({ id, slug, created_at: '', updated_at: null, created_by: {} })

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
        logic.actions.openNewGateway()
        logic.actions.setEditingGatewayValue('slug', '')
        await expectLogic(logic, () => logic.actions.submitEditingGateway()).toFinishAllListeners()
        expect(mockCreate).not.toHaveBeenCalled()
    })

    it('rejects a malformed slug without making a request', async () => {
        logic.actions.openNewGateway()
        logic.actions.setEditingGatewayValue('slug', 'Not Valid')
        await expectLogic(logic, () => logic.actions.submitEditingGateway()).toFinishAllListeners()
        expect(mockCreate).not.toHaveBeenCalled()
    })

    it('creates a gateway and closes the modal on submit', async () => {
        mockCreate.mockResolvedValue(gateway('g2', 'wizard'))
        logic.actions.openNewGateway()
        logic.actions.setEditingGatewayValue('slug', 'wizard')
        await expectLogic(logic, () => logic.actions.submitEditingGateway()).toFinishAllListeners()
        expect(mockCreate).toHaveBeenCalledWith(expect.any(String), { slug: 'wizard' })
        expect(logic.values.editingGatewayId).toBeNull()
    })

    it('renames an existing gateway via partial update', async () => {
        mockUpdate.mockResolvedValue(gateway('g1', 'renamed'))
        logic.actions.openEditGateway(gateway('g1', 'default'))
        logic.actions.setEditingGatewayValue('slug', 'renamed')
        await expectLogic(logic, () => logic.actions.submitEditingGateway()).toFinishAllListeners()
        expect(mockUpdate).toHaveBeenCalledWith(expect.any(String), 'g1', { slug: 'renamed' })
        expect(logic.values.editingGatewayId).toBeNull()
    })

    it('deletes a gateway', async () => {
        mockDestroy.mockResolvedValue(undefined as any)
        await expectLogic(logic, () => logic.actions.deleteGateway(gateway('g1', 'default'))).toFinishAllListeners()
        expect(mockDestroy).toHaveBeenCalledWith(expect.any(String), 'g1')
    })
})
