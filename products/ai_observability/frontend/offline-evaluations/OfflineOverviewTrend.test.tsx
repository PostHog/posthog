import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import * as api from '../generated/api'
import { overviewHistory, overviewScorers } from './offlineOverviewFixtures'
import { OfflineOverviewTrend } from './OfflineOverviewTrend'

jest.mock('../generated/api', () => ({
    llmAnalyticsScoreDefinitionsRetrieve: jest.fn(),
    aiObservabilityOfflineScorersHistoryList: jest.fn(),
}))

describe('OfflineOverviewTrend', () => {
    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        jest.mocked(api.llmAnalyticsScoreDefinitionsRetrieve).mockReset()
        jest.mocked(api.aiObservabilityOfflineScorersHistoryList).mockReset()
    })
    afterEach(cleanup)

    it.each([false, true])('discloses incomplete history only when the results are partial (%s)', async (partial) => {
        const scorer = overviewScorers[0]
        const results = overviewHistory(scorer)
        jest.mocked(api.llmAnalyticsScoreDefinitionsRetrieve).mockResolvedValue(scorer)
        jest.mocked(api.aiObservabilityOfflineScorersHistoryList).mockResolvedValue({
            results,
            count: partial ? 200 : results.length,
            next_cursor: partial ? 'older-results' : null,
        })

        render(
            <OfflineOverviewTrend
                teamId={997}
                scorerId={scorer.id}
                dateFrom="2026-09-01T00:00:00Z"
                dateTo="2026-09-28T00:00:00Z"
                refreshKey={0}
                timezone="UTC"
            />
        )

        await screen.findByText(scorer.name)
        expect(screen.getByText('0.851667')).toBeInTheDocument()
        expect(screen.getByText('6 experiments (570 items)')).toBeInTheDocument()
        expect(screen.getByText('Mean score')).toBeInTheDocument()
        if (partial) {
            expect(screen.getByText(/6 of 200 experiment\/version results.*Partial history/)).toBeInTheDocument()
            expect(screen.getByText('Earlier experiments and scorer versions may not be shown.')).toBeInTheDocument()
        } else {
            expect(screen.queryByText(/Partial history/)).not.toBeInTheDocument()
        }
    })
})
