import { expectLogic } from 'kea-test-utils'

import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { useMocks } from '~/mocks/jest'
import { DatabaseSchemaTable } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { viewLinkLogic } from './viewLinkLogic'

describe('viewLinkLogic', () => {
    let logic: ReturnType<typeof viewLinkLogic.build>
    let validateHandler: jest.Mock

    beforeEach(() => {
        validateHandler = jest.fn(() => [200, { is_valid: true, msg: null, hogql: null, results: [] }])
        useMocks({
            get: {
                '/api/environments/:team_id/warehouse_view_link': { results: [] },
            },
            post: {
                '/api/environments/:team_id/query/HogQLQuery': { results: [], columns: [] },
                '/api/environments/:team_id/warehouse_view_link/validate': () => validateHandler(),
            },
        })
        initKeaTests()
        logic = viewLinkLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    const fillJoin = (): void => {
        logic.actions.selectSourceTable('events')
        logic.actions.selectJoiningTable('persons')
        logic.actions.setViewLinkValue('source_table_key', 'uuid')
        logic.actions.setViewLinkValue('joining_table_key', 'id')
    }

    it('debounces rapid changes into a single validation request', async () => {
        fillJoin()

        await expectLogic(logic).toDispatchActions(['validateJoinStarted', 'validateJoinSuccess'])
        expect(validateHandler).toHaveBeenCalledTimes(1)
        expect(logic.values.joinValidation.status).toBe('valid')
    })

    it('does not validate while any join input is missing', async () => {
        logic.actions.selectSourceTable('events')
        logic.actions.selectJoiningTable('persons')
        logic.actions.setViewLinkValue('source_table_key', 'uuid')

        await expectLogic(logic).delay(900).toFinishAllListeners()
        expect(validateHandler).not.toHaveBeenCalled()
        expect(logic.values.joinValidation.status).toBe('idle')
    })

    it('blocks saving only on a query error, not on warnings', async () => {
        validateHandler.mockReturnValue([
            400,
            { attr: null, code: 'QueryError', detail: 'Field not found: uuid', type: 'query_error', hogql: null },
        ])
        fillJoin()
        await expectLogic(logic).toDispatchActions(['validateJoinFailure'])
        expect(logic.values.saveDisabledReason).toBe('Fix the join keys before saving')
        expect(logic.values.joinValidation.msg).toBe('Field not found: uuid')

        validateHandler.mockReturnValue([
            200,
            { is_valid: true, msg: 'Validation query returned no results', hogql: null, results: [] },
        ])
        logic.actions.setViewLinkValue('joining_table_key', 'id')
        await expectLogic(logic).toDispatchActions(['validateJoinSuccess'])
        expect(logic.values.saveDisabledReason).toBeNull()
        expect(logic.values.joinValidation.msg).toBe('Validation query returned no results')
    })

    it('buckets tables into picker groups and keeps unknown types reachable', async () => {
        const table = (name: string, type: string): DatabaseSchemaTable =>
            ({ name, type, fields: {}, id: name }) as unknown as DatabaseSchemaTable
        databaseTableListLogic.findMounted()?.actions.loadDatabaseSuccess({
            tables: {
                events: table('events', 'posthog'),
                stripe_customers: table('stripe_customers', 'data_warehouse'),
                my_view: table('my_view', 'view'),
                odd_one: table('odd_one', 'something_new'),
            },
        } as any)

        expect(logic.values.groupedTableOptions).toEqual([
            { value: 'PostHog tables', items: ['events'] },
            { value: 'Data warehouse', items: ['stripe_customers'] },
            { value: 'Views', items: ['my_view'] },
            { value: 'Other', items: ['odd_one'] },
        ])
    })

    it('keeps an explicit SQL expression mode even though the field is still empty', async () => {
        logic.actions.selectJoiningTable('persons')
        logic.actions.setJoiningKeyMode('sql_expression')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.joiningKeyMode).toBe('sql_expression')
    })

    it('drops the explicit key mode when the table changes', async () => {
        logic.actions.setJoiningKeyMode('sql_expression')
        logic.actions.selectJoiningTable('persons')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.joiningKeyModeOverride).toBeNull()
    })

    it('clears the key when its table changes', async () => {
        logic.actions.selectSourceTable('events')
        logic.actions.setViewLinkValue('source_table_key', 'uuid')
        logic.actions.selectSourceTable('persons')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.viewLink.source_table_key).toBeNull()
        expect(logic.values.selectedSourceKey).toBeNull()
    })

    it('keeps a field name the user typed when the joining table changes', async () => {
        logic.actions.setFieldName('my_accessor')
        logic.actions.selectJoiningTable('persons')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.fieldName).toBe('my_accessor')
    })

    it('autofills the field name from the joining table while untouched', async () => {
        logic.actions.selectJoiningTable('postgres.public.customers')
        await expectLogic(logic).toDispatchActions(['autofillFieldName'])

        expect(logic.values.fieldName).toBe('postgres_public_customers')
    })

    it('resets validation state when the modal closes', async () => {
        logic.actions.toggleJoinTableModal()
        fillJoin()
        await expectLogic(logic).toDispatchActions(['validateJoinSuccess'])
        expect(logic.values.joinValidation.status).toBe('valid')

        logic.actions.toggleJoinTableModal()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.joinValidation.status).toBe('idle')
    })
})
