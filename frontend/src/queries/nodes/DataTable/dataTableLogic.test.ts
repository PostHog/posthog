import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { expectLogic } from 'kea-test-utils'
import { dataTableLogic } from '~/queries/nodes/DataTable/dataTableLogic'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DataTableNode, NodeKind } from '~/queries/schema'

const testUniqueKey = 'testUniqueKey'

describe('dataTableLogic', () => {
    let logic: ReturnType<typeof dataTableLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/projects/:project_id/events': () => {
                    // const isOnPageFour = req.url.searchParams.get('page') === '4'
                    // debugger
                    return [
                        200,
                        {
                            results: [],
                            next: null,
                        },
                    ]
                },
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
    })

    afterEach(() => logic?.unmount())

    it('gets the response from dataNodeLogic', async () => {
        const query: DataTableNode = {
            kind: NodeKind.DataTableNode,
            source: {
                kind: NodeKind.EventsQuery,
                select: ['*', 'event', 'timestamp'],
            },
        }
        logic = dataTableLogic({
            key: testUniqueKey,
            query,
        })
        logic.mount()
        const builtDataNodeLogic = dataNodeLogic({ key: testUniqueKey, query: query.source })
        await expectLogic(logic).toMount([builtDataNodeLogic])
        await expectLogic(logic).toMatchValues({
            response: builtDataNodeLogic.values.response,
        })
    })
    it('rejects if passed anything other than a DataTableNode', async () => {})
    it('extracts sourceKind and orderBy', async () => {})
    it('adds category rows for default live events table', async () => {})
    it('updates local columns if query changed', async () => {})
    it('respects allowSorting', async () => {})
})
