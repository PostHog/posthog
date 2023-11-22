import { expectLogic } from 'kea-test-utils'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import * as libUtils from 'lib/utils'

import { useMocks } from '~/mocks/jest'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { NodeKind } from '~/queries/schema'
import { initKeaTests } from '~/test/init'

const testUniqueKey = 'testUniqueKey'

describe('dataNodeLogic - query cancellation', () => {
    let logic: ReturnType<typeof dataNodeLogic.build>

    beforeEach(async () => {
        initKeaTests()
        featureFlagLogic.mount()
        useMocks({
            get: {
                '/api/projects/:team/insights/trend/': async (req) => {
                    if (req.url.searchParams.get('date_from') === '-180d') {
                        // delay for a second before response without pausing
                        return new Promise((resolve) =>
                            setTimeout(() => {
                                resolve([200, { result: ['slow result from api'] }])
                            }, 1000)
                        )
                    }
                    return [200, { result: ['result from api'] }]
                },
            },
            post: {
                '/api/projects/997/insights/cancel/': [201],
                '/api/projects/997/query/': async () => {
                    return new Promise((resolve) =>
                        setTimeout(() => {
                            resolve([200, { result: ['slow result from api'] }])
                        }, 1000)
                    )
                },
            },
        })
    })
    afterEach(() => logic?.unmount())

    it.skip('cancels a running query', async () => {
        ;(libUtils as any).uuid = jest.fn().mockReturnValueOnce('uuid-first').mockReturnValueOnce('uuid-second')
        logic = dataNodeLogic({
            key: testUniqueKey,
            query: {
                kind: NodeKind.TrendsQuery,
                series: [],
                dateRange: { date_from: '-180d' },
            },
        })
        logic.mount()

        setTimeout(() => {
            dataNodeLogic({
                key: testUniqueKey,
                query: {
                    kind: NodeKind.TrendsQuery,
                    series: [],
                    dateRange: { date_from: '-90d' },
                },
            })
        }, 200)

        await expectLogic(logic).toDispatchActions([
            'loadData',
            'abortAnyRunningQuery',
            'loadData',
            'abortAnyRunningQuery',
            logic.actionCreators.abortQuery({ queryId: 'uuid-first' }),
            logic.actionCreators.loadDataSuccess({ result: ['result from api'] }),
        ])
    })

    it('cancels a running query on click', async () => {
        ;(libUtils as any).uuid = jest.fn().mockReturnValueOnce('uuid-first').mockReturnValueOnce('uuid-second')
        logic = dataNodeLogic({
            key: testUniqueKey,
            query: {
                kind: NodeKind.HogQLQuery,
                query: 'select * from events',
            },
        })
        logic.mount()

        setTimeout(() => {
            logic.actions.cancelQuery()
        }, 200)

        await expectLogic(logic)
            .toDispatchActions([
                'loadData',
                'abortAnyRunningQuery',
                'cancelQuery',
                'abortAnyRunningQuery',
                logic.actionCreators.abortQuery({ queryId: 'uuid-first' }),
                'loadDataFailure',
            ])
            .toMatchValues({ queryCancelled: true, response: null })
    })
})
