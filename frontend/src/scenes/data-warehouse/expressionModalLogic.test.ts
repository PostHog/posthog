import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { warehouseExpressionsList } from 'products/data_warehouse/frontend/generated/api'

import { expressionModalLogic } from './expressionModalLogic'

jest.mock('products/data_warehouse/frontend/generated/api', () => ({
    warehouseExpressionsList: jest.fn(),
}))

const mockWarehouseExpressionsList = warehouseExpressionsList as jest.Mock

describe('expressionModalLogic', () => {
    let databaseLogic: ReturnType<typeof databaseTableListLogic.build>
    let logic: ReturnType<typeof expressionModalLogic.build>

    beforeEach(() => {
        initKeaTests()
        mockWarehouseExpressionsList.mockReset().mockResolvedValue({ results: [] })
        databaseLogic = databaseTableListLogic()
        databaseLogic.mount()
        logic = expressionModalLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        databaseLogic.unmount()
    })

    it('scopes the expression editor query to the active connection', () => {
        databaseLogic.actions.setConnection('connection-123')
        logic.actions.openNewExpressionModal('auth_group')

        expect(logic.values.expressionSourceQuery).toEqual({
            kind: NodeKind.HogQLQuery,
            query: 'SELECT * FROM auth_group',
            connectionId: 'connection-123',
        })
    })
})
