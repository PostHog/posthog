import { initKeaTests } from '~/test/init'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { expectLogic, partial } from 'kea-test-utils'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { NodeKind } from '~/queries/schema'
import { query } from '~/queries/query'
jest.mock('~/queries/query')
const testUniqueKey = 'testUniqueKey'

describe('dataNodeLogic', () => {
    let logic: ReturnType<typeof dataNodeLogic.build>

    beforeEach(async () => {
        initKeaTests()
        featureFlagLogic.mount()
    })
    afterEach(() => logic?.unmount())

    it('calls query to fetch data', async () => {
        const results = {}
        ;(query as any).mockResolvedValueOnce({ results })
        logic = dataNodeLogic({
            key: testUniqueKey,
            query: {
                kind: NodeKind.EventsQuery,
                select: ['*', 'event', 'timestamp'],
            },
        })
        logic.mount()
        expect(query).toHaveBeenCalledTimes(1)
        await expectLogic(logic)
            .toMatchValues({ responseLoading: true, response: null })
            .delay(0)
            .toMatchValues({ responseLoading: false, response: partial({ results }) })

        // changing the query should trigger a new query, but keep the results while it's loading
        const results2 = {}
        ;(query as any).mockResolvedValueOnce({ results: results2 })
        dataNodeLogic({
            key: testUniqueKey,
            query: {
                kind: NodeKind.EventsQuery,
                select: ['*', 'event', 'timestamp', 'person'],
            },
        })
        expect(query).toHaveBeenCalledTimes(2)
        await expectLogic(logic)
            .toMatchValues({ responseLoading: true, response: partial({ results }) })
            .delay(0)
            .toMatchValues({ responseLoading: false, response: partial({ results: results2 }) })

        // passing in a new "deep equal" query object should not trigger a new query
        dataNodeLogic({
            key: testUniqueKey,
            query: {
                kind: NodeKind.EventsQuery,
                select: ['*', 'event', 'timestamp', 'person'],
            },
        })
        expect(query).toHaveBeenCalledTimes(2)
        await expectLogic(logic).toMatchValues({ responseLoading: false, response: partial({ results: results2 }) })

        // changing the query kind will clear the results and trigger a new query
        const results3 = {}
        ;(query as any).mockResolvedValueOnce({ results: results3 })
        dataNodeLogic({
            key: testUniqueKey,
            query: {
                kind: NodeKind.PersonsNode,
            },
        })
        expect(query).toHaveBeenCalledTimes(3)
        await expectLogic(logic)
            .toMatchValues({ responseLoading: true, response: null })
            .delay(0)
            .toMatchValues({ responseLoading: false, response: partial({ results: results3 }) })
    })

    it('can load new data if EventsQuery sorted by timestamp', async () => {})
    it('can autoload new data for EventsQuery', async () => {})
    it('will highlight new rows for EventsQuery', async () => {})
    it('can load next data for EventsQuery', async () => {})
    it('can load next data for PersonsNode', async () => {})
})
