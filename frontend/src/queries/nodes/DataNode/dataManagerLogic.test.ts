import { initKeaTests } from '~/test/init'
import { expectLogic } from 'kea-test-utils'

import { dataManagerLogic } from '~/queries/nodes/DataNode/dataManagerLogic'
import { NodeKind, TrendsQuery } from '~/queries/schema'
import { connect, kea, selectors } from 'kea'
import { useMocks } from '~/mocks/jest'

// jest.mock('~/queries/query')

const TEST_QUERY_ID = 'test-id'

const dummyLogic = kea([
    connect({
        values: [dataManagerLogic, ['getQueryLoading', 'getQueryResponse', 'getQueryError']],
    }),
    selectors({
        dummyLoading: [(s) => [s.getQueryLoading], (getQueryLoading) => getQueryLoading(TEST_QUERY_ID)],
        dummyResponse: [(s) => [s.getQueryResponse], (getQueryResponse) => getQueryResponse(TEST_QUERY_ID)],
        dummyError: [(s) => [s.getQueryError], (getQueryError) => getQueryError(TEST_QUERY_ID)],
    }),
])

describe('dataManagerLogic', () => {
    let logic: ReturnType<typeof dataManagerLogic.build>

    beforeEach(async () => {
        initKeaTests()
        logic = dataManagerLogic()
        logic.mount()
    })
    afterEach(() => logic?.unmount())

    it('with valid response', async () => {
        useMocks({
            get: { '/api/projects/:team/insights/trend/': { result: ['result from api'] } },
        })
        dummyLogic.mount()

        const query: TrendsQuery = {
            kind: NodeKind.TrendsQuery,
            series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
        }

        await expectLogic(logic, () => {
            logic.actions.runQuery(TEST_QUERY_ID, query)
        })
            // .toDispatchActions(dataNodeLogic.findMounted({ key: TEST_QUERY_ID }), ['loadResults', 'loadResultsSuccess'])
            // .toMatchValues(dummyLogic, {
            //     dummyLoading: true,
            //     // dummyResponse: { a: 1 },
            // })
            .toFinishAllListeners()
            // .delay(0)
            .toMatchValues(dummyLogic, {
                dummyLoading: false,
                dummyResponse: { result: ['result from api'] },
            })
    })

    it('with error response', async () => {
        useMocks({
            get: { '/api/projects/:team/insights/trend/': [500, { status: 0, detail: 'error from api' }] },
        })
        dummyLogic.mount()

        const query: TrendsQuery = {
            kind: NodeKind.TrendsQuery,
            series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
        }

        await expectLogic(logic, () => {
            logic.actions.runQuery(TEST_QUERY_ID, query)
        })
            // .toDispatchActions(dataNodeLogic.findMounted({ key: TEST_QUERY_ID }), ['loadResults', 'loadResultsSuccess'])
            // .toMatchValues(dummyLogic, {
            //     dummyLoading: true,
            //     // dummyResponse: { a: 1 },
            // })
            .toFinishAllListeners()
            // .delay(0)
            .toMatchValues(dummyLogic, {
                dummyLoading: false,
                // dummyResponse: { result: ['result from api'] },
                dummyError: { a: 1 },
            })
    })
})
