import { cleanup, render, screen, waitFor } from '@testing-library/react'

import { performQuery } from '~/queries/query'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { AccountProductUsage } from './AccountProductUsage'
import { BOOK_ACTIVITY_MATRIX_MOCK } from './bookActivityMatrixMock'

jest.mock('~/queries/query', () => ({ performQuery: jest.fn() }))
const query = performQuery as jest.Mock
const result = {
    ...BOOK_ACTIVITY_MATRIX_MOCK,
    columns: [{ key: '2026-11-02', partial: true }],
    data: [{ row: 'one', column: '2026-11-02', series: 'pa', users: 5 }],
    firstUse: [{ row: 'one', series: 'pa', date: '2026-11-02' }],
}
const person = {
    row: 'one',
    column: '2026-11-02',
    series: 'pa',
    personId: 'alice',
    label: 'Alice',
    rank: 1,
    actionCount: 4,
    engagedSeconds: 0,
    actions: [],
    topPaths: [],
}
const props = {
    result,
    accountId: 'one',
    instanceId: 'history',
    includeFirstUse: true,
    onIncludeFirstUseChange: () => {},
}

describe('AccountProductUsage history', () => {
    beforeEach(() => {
        initKeaTests()
        query.mockReset()
    })
    afterEach(cleanup)
    it('trusts all-history account dates instead of a false current-period matrix first use', async () => {
        query.mockImplementation((request) =>
            Promise.resolve({
                results:
                    request.kind === NodeKind.BookActivityPeopleQuery
                        ? { rows: [], columns: [], people: [person], truncated: false }
                        : {
                              rows: [],
                              people: [],
                              accounts: [{ row: 'one', series: 'pa', date: '2019-01-01' }],
                              truncated: false,
                          },
            })
        )
        render(<AccountProductUsage {...props} />)
        expect(await screen.findByText('Alice')).toBeTruthy()
        expect(screen.queryByRole('img', { name: 'First use ever' })).toBeNull()
    })
    it('keeps names and counts while loading firsts, then hides marks immediately when switched off', async () => {
        let finishFirsts!: (value: unknown) => void
        query.mockImplementation((request) =>
            request.kind === NodeKind.BookActivityPeopleQuery
                ? Promise.resolve({ results: { rows: [], columns: [], people: [person], truncated: false } })
                : new Promise((resolve) => {
                      finishFirsts = resolve
                  })
        )
        const { rerender } = render(<AccountProductUsage {...props} includeFirstUse={false} />)
        expect(await screen.findByText('Alice')).toBeTruthy()
        rerender(<AccountProductUsage {...props} />)
        expect(screen.getByText('Alice')).toBeTruthy()
        await waitFor(() =>
            expect(
                query.mock.calls.filter(([request]) => request.kind === NodeKind.BookActivityFirstsQuery)
            ).toHaveLength(1)
        )
        expect(query.mock.calls.filter(([request]) => request.kind === NodeKind.BookActivityPeopleQuery)).toHaveLength(
            1
        )
        finishFirsts({
            results: {
                rows: [],
                people: [],
                accounts: [{ row: 'one', series: 'pa', date: '2026-11-03' }],
                truncated: false,
            },
        })
        expect(await screen.findByRole('img', { name: 'First use ever' })).toBeTruthy()
        rerender(<AccountProductUsage {...props} includeFirstUse={false} />)
        expect(screen.queryByRole('img', { name: 'First use ever' })).toBeNull()
        expect(screen.getByText('Alice')).toBeTruthy()
    })
})
