import { fireEvent, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { AccountProductUsagePeople } from './AccountProductUsagePeople'

describe('AccountProductUsagePeople', () => {
    it('shows a compact full-week summary and exposes qualifications on demand', () => {
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
                firsts={[]}
                total={5}
                columnKey="2026-11-01"
                productLabel="Product analytics"
                showDetails
            />
        )
        expect(screen.getByText('Product analytics · 5 users')).toBeTruthy()
        expect(screen.getByText('2m · 4 actions')).toBeTruthy()
        expect(screen.getByText('Nov 1')).toBeTruthy()
        expect(screen.getByText('Nov 7, 2026')).toBeTruthy()
        fireEvent.click(screen.getByRole('button', { name: 'Qualification details' }))
        expect(screen.getAllByText('Alice').length).toBeGreaterThan(0)
        expect(screen.getByText('4 actions, 120 seconds on product pages')).toBeTruthy()
        expect(screen.getByText('insight viewed: 4')).toBeTruthy()
        expect(screen.getByText('/insights: 120 seconds')).toBeTruthy()
        expect(screen.getByText('+4 more')).toBeTruthy()
    })
})
