import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
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
