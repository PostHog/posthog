import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { overviewHistory, overviewScorers } from './offlineOverviewFixtures'
import { OfflineSummaryMetrics } from './OfflineScoreSummaryDisplay'

describe('OfflineSummaryMetrics', () => {
    it.each([
        { scorer: overviewScorers[0], rule: 'Pass when score ≥ 0.8', verdict: 'Mean 0.64 · Failed' },
        { scorer: overviewScorers[2], rule: 'Pass when score ≤ 1800', verdict: 'Mean 1400 · Passed' },
    ])('shows the pinned rule and item pass rate on bar hover ($rule)', async ({ scorer, rule, verdict }) => {
        const { summary } = overviewHistory(scorer)[0]
        const { container } = render(<OfflineSummaryMetrics summary={summary} />)
        const bar = container.querySelector('.LemonProgress')!

        await userEvent.hover(bar)

        expect(await screen.findByText(`${rule} ${verdict} 65 of 95 scored items passed (68.42%)`)).toBeVisible()
    })
})
