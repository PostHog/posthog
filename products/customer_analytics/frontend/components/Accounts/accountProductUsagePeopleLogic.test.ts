import { expectLogic } from 'kea-test-utils'

import { cancelQueryOnServer } from '~/queries/nodes/DataNode/dataNodeLogic'
import { performQuery } from '~/queries/query'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { BOOK_ACTIVITY_MATRIX_MOCK } from '../../__mocks__/bookActivityMatrixMock'
import { accountProductUsagePeopleLogic } from './accountProductUsagePeopleLogic'

jest.mock('~/queries/query', () => ({ performQuery: jest.fn() }))
jest.mock('~/queries/nodes/DataNode/dataNodeLogic', () => ({
    ...jest.requireActual('~/queries/nodes/DataNode/dataNodeLogic'),
    cancelQueryOnServer: jest.fn(),
}))
const query = performQuery as jest.Mock
const result = {
    ...BOOK_ACTIVITY_MATRIX_MOCK,
    columns: [
        { key: '2026-10-26', partial: false },
        { key: '2026-11-02', partial: true },
    ],
    data: [{ row: 'account', column: '2026-11-02', series: 'pa', users: 5 }],
}
const props = { instanceId: 'people-test', accountId: 'account', result, includeFirstUse: false }
const empty = { rows: [], columns: [], people: [], truncated: false }

describe('accountProductUsagePeopleLogic', () => {
    beforeEach(() => {
        initKeaTests()
        query.mockReset()
        ;(cancelQueryOnServer as jest.Mock).mockReset()
        query.mockResolvedValue({ results: empty })
    })
    it('loads top three people per week for this account without scanning history by default', async () => {
        const logic = accountProductUsagePeopleLogic(props)
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadDetailsSuccess'])
        expect(query).toHaveBeenCalledTimes(1)
        expect(query.mock.calls[0][0]).toMatchObject({
            kind: NodeKind.BookActivityPeopleQuery,
            accountIds: ['account'],
            interval: 'week',
            peopleLimit: 5,
            dateRange: { date_from: '2026-10-26', date_to: null },
        })
        expect(logic.values.details?.firsts).toBeNull()
        logic.unmount()
        expect(cancelQueryOnServer).not.toHaveBeenCalled()
    })
    it('loads history only after explicit opt in and never queries an empty account', async () => {
        const logic = accountProductUsagePeopleLogic({ ...props, includeFirstUse: true })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadDetailsSuccess'])
        expect(query.mock.calls.map(([request]) => request.kind)).toEqual([
            NodeKind.BookActivityPeopleQuery,
            NodeKind.BookActivityFirstsQuery,
        ])
        logic.unmount()
        query.mockClear()
        const inactive = accountProductUsagePeopleLogic({ ...props, accountId: 'inactive' })
        inactive.mount()
        await expectLogic(inactive).toDispatchActions(['loadDetailsSuccess'])
        expect(query).not.toHaveBeenCalled()
        inactive.unmount()
    })
    it('aborts and cancels outstanding server work on unmount', async () => {
        query.mockImplementation(() => new Promise(() => {}))
        const logic = accountProductUsagePeopleLogic(props)
        logic.mount()
        const options = query.mock.calls[0][1]
        const queryId = query.mock.calls[0][3]
        logic.unmount()
        expect(options.signal.aborted).toBe(true)
        expect(cancelQueryOnServer).toHaveBeenCalledWith(expect.anything(), queryId)
    })
    it('keeps a replaced request from cancelling or replacing its successor', async () => {
        let rejectFirst!: (error: Error) => void
        query.mockImplementationOnce(
            () =>
                new Promise((_, reject) => {
                    rejectFirst = reject
                })
        )
        const logic = accountProductUsagePeopleLogic(props)
        logic.mount()
        await expectLogic(logic, () => logic.actions.loadDetails()).toDispatchActions(['loadDetailsSuccess'])
        rejectFirst(new Error('aborted old request'))
        await expectLogic(logic).toFinishAllListeners()
        expect(query.mock.calls[1][1].signal.aborted).toBe(false)
        expect(logic.values.details?.people).toEqual(empty)
        expect(logic.values.error).toBeNull()
        logic.unmount()
    })
})
