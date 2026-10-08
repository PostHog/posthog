import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import * as api from '../generated/api'
import { detailExperiment, detailItems, detailSummaries, makeOfflineDetailCells } from './offlineDetailFixtures'
import { OfflineExperimentContent } from './OfflineExperimentContent'

jest.mock('../generated/api', () => ({
    aiObservabilityOfflineExperimentsRetrieve: jest.fn(),
    aiObservabilityOfflineExperimentsScorerSummariesList: jest.fn(),
    aiObservabilityOfflineExperimentsItemsList: jest.fn(),
    aiObservabilityOfflineExperimentsResultCellsRetrieve: jest.fn(),
    aiObservabilityOfflineExperimentsCompleteCreate: jest.fn(),
}))

const readSummaries = jest.mocked(api.aiObservabilityOfflineExperimentsScorerSummariesList)

describe('OfflineExperimentContent', () => {
    afterEach(cleanup)
    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        jest.mocked(api.aiObservabilityOfflineExperimentsRetrieve).mockResolvedValue(detailExperiment)
        readSummaries.mockResolvedValue({ count: 25, next_cursor: null, results: detailSummaries })
        jest.mocked(api.aiObservabilityOfflineExperimentsItemsList).mockResolvedValue({
            count: 8,
            next_cursor: null,
            results: detailItems,
            scorer_versions: [],
        })
        jest.mocked(api.aiObservabilityOfflineExperimentsResultCellsRetrieve).mockImplementation(
            async (_team, _experiment, params) =>
                makeOfflineDetailCells(params.item_ids.split(','), params.scorer_version_ids.split(','))
        )
    })

    it('keeps a scorer summary panel the user opened open after a refresh', async () => {
        render(<OfflineExperimentContent teamId={997} experimentId={detailExperiment.id} />)
        const title = await screen.findByText('Scorer summaries (25)')
        const panel = title.closest('details') as HTMLDetailsElement
        expect(panel.open).toBe(false)
        panel.open = true

        fireEvent.click(screen.getByText('Refresh'))
        await waitFor(() => expect(readSummaries).toHaveBeenCalledTimes(2))
        await screen.findByText('Scorer summaries (25)')

        expect(panel.open).toBe(true)
    })
})
