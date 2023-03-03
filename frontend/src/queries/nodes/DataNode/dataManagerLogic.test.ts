import { initKeaTests } from '~/test/init'
import { expectLogic, partial } from 'kea-test-utils'

import { dataManagerLogic } from '~/queries/nodes/DataNode/dataManagerLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { NodeKind, TrendsQuery } from '~/queries/schema'
import { query } from '~/queries/query'

// jest.mock('~/queries/query')

describe('dataManagerLogic', () => {
    let logic: ReturnType<typeof dataManagerLogic.build>

    beforeEach(async () => {
        initKeaTests()
        // featureFlagLogic.mount()
        logic = dataManagerLogic()
        logic.mount()
    })
    afterEach(() => logic?.unmount())

    it('calls query to fetch data', async () => {
        const query: TrendsQuery = {
            kind: NodeKind.TrendsQuery,
            series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
        }

        await expectLogic(logic, () => {
            logic.actions.runQuery({ queryId: 'my-uuid', queryObject: query })
        })
            .toMatchValues({ queries: true })
            .delay(0)
            .toMatchValues({ queries: false })

        // const results = {}
        // ;(query as any).mockResolvedValueOnce({ results })
        // expect(query).toHaveBeenCalledTimes(1)
        // await expectLogic(logic)
        //     .toMatchValues({ responseLoading: true, response: null })
        //     .delay(0)
        //     .toMatchValues({ responseLoading: false, response: partial({ results }) })
        // // changing the query should trigger a new query, but keep the results while it's loading
        // const results2 = {}
        // ;(query as any).mockResolvedValueOnce({ results: results2 })
        // dataManagerLogic({
        //     key: testUniqueKey,
        //     query: {
        //         kind: NodeKind.EventsQuery,
        //         select: ['*', 'event', 'timestamp', 'person'],
        //     },
        // })
        // expect(query).toHaveBeenCalledTimes(2)
        // await expectLogic(logic)
        //     .toMatchValues({ responseLoading: true, response: partial({ results }) })
        //     .delay(0)
        //     .toMatchValues({ responseLoading: false, response: partial({ results: results2 }) })
        // // passing in a new "deep equal" query object should not trigger a new query
        // dataManagerLogic({
        //     key: testUniqueKey,
        //     query: {
        //         kind: NodeKind.EventsQuery,
        //         select: ['*', 'event', 'timestamp', 'person'],
        //     },
        // })
        // expect(query).toHaveBeenCalledTimes(2)
        // await expectLogic(logic).toMatchValues({ responseLoading: false, response: partial({ results: results2 }) })
        // // changing the query kind will clear the results and trigger a new query
        // const results3 = {}
        // ;(query as any).mockResolvedValueOnce({ results: results3 })
        // dataManagerLogic({
        //     key: testUniqueKey,
        //     query: {
        //         kind: NodeKind.PersonsNode,
        //     },
        // })
        // expect(query).toHaveBeenCalledTimes(3)
        // await expectLogic(logic)
        //     .toMatchValues({ responseLoading: true, response: null })
        //     .delay(0)
        //     .toMatchValues({ responseLoading: false, response: partial({ results: results3 }) })
    })
})
