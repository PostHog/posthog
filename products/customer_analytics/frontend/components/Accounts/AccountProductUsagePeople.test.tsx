import { render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { AccountProductUsagePeople } from './AccountProductUsagePeople'

it('includes each weekly user qualification directly in cell tooltip content', () => {
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
            showDetails
        />
    )
    expect(screen.getByText('Alice')).toBeTruthy()
    expect(screen.getByText('4 actions, 120 seconds on product pages')).toBeTruthy()
    expect(screen.getByText('insight viewed: 4')).toBeTruthy()
    expect(screen.getByText('/insights: 120 seconds')).toBeTruthy()
    expect(screen.getByText('+4 more')).toBeTruthy()
})
