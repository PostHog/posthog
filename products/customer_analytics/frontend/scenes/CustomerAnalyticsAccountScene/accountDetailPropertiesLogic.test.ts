import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import {
    accountRelationshipDefinitionsList,
    accountsCustomPropertyValuesCreate,
    accountsCustomPropertyValuesList,
    accountsRelationshipsList,
    customPropertyDefinitionsList,
} from 'products/customer_analytics/frontend/generated/api'
import type { CustomPropertyValueApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { accountDetailPropertiesLogic } from './accountDetailPropertiesLogic'

jest.mock('products/customer_analytics/frontend/generated/api', () => ({
    ...jest.requireActual('products/customer_analytics/frontend/generated/api'),
    accountRelationshipDefinitionsList: jest.fn(),
    accountsCustomPropertyValuesCreate: jest.fn(),
    accountsCustomPropertyValuesList: jest.fn(),
    accountsRelationshipsList: jest.fn(),
    customPropertyDefinitionsList: jest.fn(),
}))

const mockAccountRelationshipDefinitionsList = accountRelationshipDefinitionsList as jest.MockedFunction<
    typeof accountRelationshipDefinitionsList
>
const mockAccountsCustomPropertyValuesCreate = accountsCustomPropertyValuesCreate as jest.MockedFunction<
    typeof accountsCustomPropertyValuesCreate
>
const mockAccountsCustomPropertyValuesList = accountsCustomPropertyValuesList as jest.MockedFunction<
    typeof accountsCustomPropertyValuesList
>
const mockAccountsRelationshipsList = accountsRelationshipsList as jest.MockedFunction<typeof accountsRelationshipsList>
const mockCustomPropertyDefinitionsList = customPropertyDefinitionsList as jest.MockedFunction<
    typeof customPropertyDefinitionsList
>

const ACCOUNT_ID = '0190da51-0b0e-7000-8000-000000000001'
const DEFINITION_ID = '0190da51-0b0e-7000-8000-000000000002'

describe('accountDetailPropertiesLogic', () => {
    let logic: ReturnType<typeof accountDetailPropertiesLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
        mockAccountRelationshipDefinitionsList.mockResolvedValue({ count: 0, results: [] })
        mockAccountsCustomPropertyValuesList.mockResolvedValue([])
        mockAccountsRelationshipsList.mockResolvedValue([])
        mockCustomPropertyDefinitionsList.mockResolvedValue({ count: 0, results: [] })
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('saves once, renders the optimistic value, and clears the in-flight state', async () => {
        let resolveSave: (value: CustomPropertyValueApi) => void
        mockAccountsCustomPropertyValuesCreate.mockReturnValue(
            new Promise<CustomPropertyValueApi>((resolve) => {
                resolveSave = resolve
            })
        )
        logic = accountDetailPropertiesLogic({ accountId: ACCOUNT_ID })
        logic.mount()

        await expectLogic(logic).toDispatchActions([
            'loadDefinitionsSuccess',
            'loadRelationshipDefinitionsSuccess',
            'loadCustomValuesSuccess',
            'loadRelationshipsSuccess',
        ])

        logic.actions.saveCustomPropertyValue(DEFINITION_ID, 42)
        logic.actions.saveCustomPropertyValue(DEFINITION_ID, 43)

        expect(mockAccountsCustomPropertyValuesCreate).toHaveBeenCalledTimes(1)
        expect(mockAccountsCustomPropertyValuesCreate).toHaveBeenCalledWith(expect.any(String), ACCOUNT_ID, {
            definition: DEFINITION_ID,
            value: 42,
        })
        expect(logic.values.valueByDefinitionId[DEFINITION_ID]).toBe(42)
        expect(logic.values.isPropertySaving(`custom:${DEFINITION_ID}`)).toBe(true)

        resolveSave!({
            id: 'value-1',
            account_id: ACCOUNT_ID,
            definition_id: DEFINITION_ID,
            value: 42,
            created_at: '2026-01-01T00:00:00Z',
            created_by_id: 1,
        })
        await expectLogic(logic).toDispatchActions(['saveCustomPropertyValueDone'])

        expect(logic.values.valueByDefinitionId[DEFINITION_ID]).toBe(42)
        expect(logic.values.isPropertySaving(`custom:${DEFINITION_ID}`)).toBe(false)
    })
})
