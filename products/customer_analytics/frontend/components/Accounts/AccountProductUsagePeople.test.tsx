import { fireEvent, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { AccountProductUsagePeople } from './AccountProductUsagePeople'

describe('AccountProductUsagePeople', () => {
    it('shows a compact full-week summary and opens qualifications on request', () => {
        const inspect = jest.fn()
        initKeaTests()
        render(
            <AccountProductUsagePeople
                people={[
                    {
                        row: 'one',
                        column: '2026-11-01',
                        series: 'pa',
                        personId: 'alice',
                        label: 'Alice',
                        rank: 1,
                        actionCount: 4,
                        engagedSeconds: 120,
                        actions: [{ event: 'insight viewed', count: 4 }],
                        topPaths: [{ path: '/insights', seconds: 120 }],
                    },
                ]}
                total={5}
                columnKey="2026-11-01"
                productLabel="Product analytics"
                onInspect={inspect}
                showDetails
            />
        )
        expect(screen.getByText('Product analytics · 5 users')).toBeTruthy()
        expect(screen.getByText('2m · 4 actions')).toBeTruthy()
        expect(screen.getByText('Nov 1')).toBeTruthy()
        expect(screen.getByText('Nov 7, 2026')).toBeTruthy()
        fireEvent.click(screen.getByRole('button', { name: 'Qualification details' }))
        expect(inspect).toHaveBeenCalledTimes(1)
        expect(screen.getByText('+4 more')).toBeTruthy()
    })
})
