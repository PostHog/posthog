import { BuiltLogic } from 'kea'
import { mockAPI } from 'lib/api.mock'
import { expectLogic, initKeaTestLogic } from '~/test/kea-test-utils'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { trendsLogicType } from 'scenes/trends/trendsLogicType'
import { PropertyOperator } from '~/types'

jest.mock('lib/api')

describe('trendsLogic', () => {
    let logic: BuiltLogic<trendsLogicType>

    mockAPI(async ({ pathname, searchParams }) => {
        if (pathname === '_preflight/') {
            return { is_clickhouse_enabled: true }
        } else if (pathname === 'api/users/@me/') {
            return { organization: {}, team: { ingested_event: true, completed_snippet_onboarding: true } }
        } else if (
            [
                'api/action/',
                'api/projects/@current/event_definitions/',
                'api/users/@me/',
                'api/dashboard',
                'api/insight',
            ].includes(pathname)
        ) {
            return { results: [] }
        } else if (['api/insight/session/', 'api/insight/trend/'].includes(pathname)) {
            return { result: [] }
        } else {
            debugger
            throw new Error(`Unmocked fetch to: ${pathname} with params: ${JSON.stringify(searchParams)}`)
        }
    })

    initKeaTestLogic({
        logic: trendsLogic,
        props: {},
        onLogic: (l) => (logic = l),
    })

    describe('core assumptions', () => {
        it('loads results on mount', async () => {
            await expectLogic(logic).toDispatchActions(['loadResults'])
        })
    })

    describe('setCachedResults', () => {
        it('sets results and filters', async () => {
            await expectLogic(logic)
                .toDispatchActions(['loadResultsSuccess'])
                .toMatchValues({
                    results: [],
                    loadedFilters: expect.objectContaining({ properties: [] }),
                    filters: expect.objectContaining({ properties: [] }),
                })

            logic.actions.setCachedResults(
                { properties: [{ value: 'lol', operator: PropertyOperator.Exact, key: 'lol', type: 'lol' }] },
                ['result']
            )

            await expectLogic(logic)
                .toDispatchActions(['setCachedResults', 'setCachedResultsSuccess', 'setFilters'])
                .toMatchValues({
                    results: ['result'],
                    loadedFilters: expect.objectContaining({ properties: [expect.objectContaining({ type: 'lol' })] }),
                    filters: expect.objectContaining({ properties: [expect.objectContaining({ type: 'lol' })] }),
                })
        })
    })
})
