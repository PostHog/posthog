import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'

import { performQuery } from '~/queries/query'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { BOOK_ACTIVITY_MATRIX_MOCK } from '../../__mocks__/bookActivityMatrixMock'
import { AccountProductUsage } from './AccountProductUsage'

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
    engagedSeconds: 120,
    actions: [{ event: 'insight viewed', count: 4 }],
    topPaths: [{ path: '/insights', seconds: 120 }],
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
    it.each(['weekly', 'latest'])(
        'dismisses the %s tooltip when opening stable qualification details',
        async (source) => {
            query.mockResolvedValue({ results: { rows: [], columns: [], people: [person], truncated: false } })
            render(<AccountProductUsage {...props} includeFirstUse={false} />)
            await screen.findByText('Alice +4')
            const cell =
                source === 'weekly'
                    ? screen.getByLabelText('Product analytics users: 5').closest('.DotMatrix__cell')!
                    : screen.getByText('Alice +4')
            fireEvent.focus(cell)
            fireEvent.click(await screen.findByText('Qualification details'))
            await waitFor(() => expect(screen.queryByRole('tooltip')).toBeNull())
            expect(screen.getAllByText('Product analytics · 5 users')).toHaveLength(1)
            fireEvent.blur(cell)
            fireEvent.mouseLeave(cell)
            const modal = await screen.findByRole('dialog')
            expect(within(modal).getByText('4 actions, 120 seconds on product pages')).toBeTruthy()
            expect(within(modal).getByText('insight viewed: 4')).toBeTruthy()
            expect(within(modal).getByText('/insights: 120 seconds')).toBeTruthy()
            fireEvent.click(within(modal).getByLabelText('close'))
            await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
            expect(screen.queryByRole('tooltip')).toBeNull()
        }
    )

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
        expect(await screen.findByText('Alice +4')).toBeTruthy()
        expect(screen.queryByLabelText('First use ever')).toBeNull()
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
        expect(await screen.findByText('Alice +4')).toBeTruthy()
        rerender(<AccountProductUsage {...props} />)
        expect(screen.getByText('Alice +4')).toBeTruthy()
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
        expect(await screen.findByLabelText('First use ever')).toBeTruthy()
        rerender(<AccountProductUsage {...props} includeFirstUse={false} />)
        expect(screen.queryByLabelText('First use ever')).toBeNull()
        expect(screen.getByText('Alice +4')).toBeTruthy()
    })
})
