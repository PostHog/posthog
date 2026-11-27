import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import * as api from '../generated/api'
import { overviewExperiments, overviewHistory, overviewScorers } from './offlineOverviewFixtures'
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

    it('shows boolean run outcomes from their pinned versions, including false and unavailable results', async () => {
        const definition = { ...overviewScorers[1], scope: 'experiment' as const, calculation: 'composite' as const }
        const score = {
            definition_id: definition.id,
            name: definition.name,
            config: definition.config,
            kind: definition.kind,
            scorer_version_id: 'v1',
            version: 1,
            inputs: [],
        }
        jest.mocked(api.llmAnalyticsScoreDefinitionsRetrieve).mockResolvedValue(definition)
        jest.mocked(api.aiObservabilityOfflineScorersHistoryList).mockResolvedValue({
            count: 2,
            next: null,
            previous: null,
            next_cursor: null,
            results: [
                {
                    experiment: {
                        ...overviewExperiments[1],
                        experiment_score: { ...score, status: 'ok', value: false, passed: false },
                    },
                    summary: null,
                },
                {
                    experiment: {
                        ...overviewExperiments[2],
                        experiment_score: { ...score, status: 'missing_input', value: null, passed: null },
                    },
                    summary: null,
                },
            ],
        })
        render(
            <OfflineOverviewTrend
                teamId={997}
                scorerId={definition.id}
                dateTo="2026-09-28T00:00:00Z"
                refreshKey={0}
                timezone="UTC"
            />
        )
        expect(await screen.findByText('1 of 2 runs scored')).toBeInTheDocument()
        expect(screen.getByText('Ungrounded')).toBeVisible()
        expect(screen.getByText('Missing scorer results')).toBeVisible()
        expect(screen.getByText(overviewExperiments[1].name).closest('a')).toHaveAttribute(
            'href',
            expect.stringContaining(overviewExperiments[1].id)
        )
    })

    it.each([false, true])('discloses incomplete history only when the results are partial (%s)', async (partial) => {
        const scorer = overviewScorers[0]
        const results = overviewHistory(scorer)
        jest.mocked(api.llmAnalyticsScoreDefinitionsRetrieve).mockResolvedValue({
            ...scorer,
            current_version: 3,
            current_version_id: 'newer-version-with-no-results',
        })
        jest.mocked(api.aiObservabilityOfflineScorersHistoryList).mockImplementation(async (_team, _scorer, query) => {
            const pageIndex = Number(query?.cursor || 0)
            return {
                results: results.map((point) => ({
                    ...point,
                    experiment: { ...point.experiment, id: `${point.experiment.id}-${pageIndex}` },
                })),
                count: partial ? 200 : results.length,
                next: null,
                previous: null,
                next_cursor: partial ? String(pageIndex + 1) : null,
            }
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
        expect(screen.getByText(scorer.name).closest('a')).toHaveAttribute(
            'href',
            expect.stringContaining(`version=${results[0].summary.scorer.id}`)
        )
        expect(screen.getByText('0.851667')).toBeInTheDocument()
        expect(
            screen.getByText(partial ? '30 experiments (2850 items)' : '6 experiments (570 items)')
        ).toBeInTheDocument()
        expect(screen.getByText('Mean score')).toBeInTheDocument()
        if (partial) {
            expect(screen.getByText(/30 of 200 history points.*Partial history/)).toBeInTheDocument()
            expect(screen.getByText('Earlier experiments and scorer versions may not be shown.')).toBeInTheDocument()
        } else {
            expect(screen.queryByText(/Partial history/)).not.toBeInTheDocument()
        }
    })
})
