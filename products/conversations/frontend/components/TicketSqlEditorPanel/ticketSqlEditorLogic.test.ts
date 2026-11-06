import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { UserUIConfiguration } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { UserType } from '~/types'

import { DEFAULT_TICKET_SQL_QUERY, ticketSqlEditorLogic } from './ticketSqlEditorLogic'

const PERSON_ID = '018f0000-0000-7000-8000-000000000001'
const DISTINCT_ID = 'customer-1'
const CUSTOM_QUERY = 'SELECT count() FROM events WHERE distinct_id = {distinct_id}'

describe('ticketSqlEditorLogic', () => {
    let logic: ReturnType<typeof ticketSqlEditorLogic.build>
    let sentQuery: Record<string, unknown> | null
    let patchedUser: Partial<UserType> | null

    function setUp(uiConfiguration: UserUIConfiguration | null): void {
        initKeaTests()
        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, ui_configuration: uiConfiguration })
        logic = ticketSqlEditorLogic({ personId: PERSON_ID, distinctId: DISTINCT_ID })
        logic.mount()
    }

    beforeEach(() => {
        sentQuery = null
        patchedUser = null
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': async ({ request }) => {
                    sentQuery = ((await request.json()) as { query: Record<string, unknown> }).query
                    return [200, { columns: ['count()'], results: [[3]] }]
                },
            },
            patch: {
                '/api/users/@me/': async ({ request }) => {
                    patchedUser = (await request.json()) as Partial<UserType>
                    return [200, { ...MOCK_DEFAULT_USER, ...patchedUser }]
                },
            },
        })
    })

    afterEach(() => {
        logic.unmount()
    })

    it("runs the query with the ticket's customer as placeholders and saves it, keeping other UI settings", async () => {
        setUp({ version: 1, ticket_sidebar: { hidden: ['exceptions'] } })

        await expectLogic(logic, () => {
            logic.actions.setQueryInput(CUSTOM_QUERY)
            logic.actions.runQuery(CUSTOM_QUERY)
        })
            .toDispatchActions(['runQuerySuccess'])
            .toFinishAllListeners()
            .toMatchValues({ result: { columns: ['count()'], rows: [[3]] }, queryError: null })

        expect(sentQuery).toMatchObject({
            query: CUSTOM_QUERY,
            values: { person_id: PERSON_ID, distinct_id: DISTINCT_ID },
        })
        expect(patchedUser?.ui_configuration).toEqual({
            version: 1,
            ticket_sidebar: { hidden: ['exceptions'] },
            ticket_sidebar_sql_query: CUSTOM_QUERY,
        })
    })

    it('running the default query after a saved one clears the stored query', async () => {
        setUp({ version: 1, ticket_sidebar_sql_query: CUSTOM_QUERY })
        expect(logic.values.editorQuery).toEqual(CUSTOM_QUERY)

        await expectLogic(logic, () => {
            logic.actions.resetQuery()
            logic.actions.runQuery(DEFAULT_TICKET_SQL_QUERY)
        })
            .toDispatchActions(['runQuerySuccess'])
            .toFinishAllListeners()

        expect(patchedUser?.ui_configuration).toEqual({ version: 1 })
    })
})
