import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { ApiError } from 'lib/api-error'

import { initKeaTests } from '~/test/init'

import * as api from '../generated/api'
import type { OfflineResultReadApi } from '../generated/api.schemas'
import { detailExperiment, detailItems, offlineDetailItemResults } from './offlineDetailFixtures'
import { OfflineItemInspector } from './OfflineItemInspector'

jest.mock('../generated/api', () => ({
    aiObservabilityOfflineExperimentsItemsRetrieve: jest.fn(),
    aiObservabilityOfflineExperimentsItemsPayloadRetrieve: jest.fn(),
    aiObservabilityOfflineExperimentsItemsResultsList: jest.fn(),
    aiObservabilityOfflineExperimentsResultsPayloadRetrieve: jest.fn(),
}))

describe('OfflineItemInspector', () => {
    afterEach(cleanup)
    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        jest.mocked(api.aiObservabilityOfflineExperimentsItemsRetrieve).mockReset()
        jest.mocked(api.aiObservabilityOfflineExperimentsItemsPayloadRetrieve).mockReset()
        jest.mocked(api.aiObservabilityOfflineExperimentsItemsResultsList).mockReset()
        jest.mocked(api.aiObservabilityOfflineExperimentsResultsPayloadRetrieve).mockReset()
    })

    it('displays the stored evaluator error message for the selected result', async () => {
        const result: OfflineResultReadApi = {
            ...offlineDetailItemResults(detailItems[0].id)[0],
            status: 'error',
            value: null,
            error_code: 'evaluator_timeout',
        }
        jest.mocked(api.aiObservabilityOfflineExperimentsItemsRetrieve).mockResolvedValue(detailItems[0])
        jest.mocked(api.aiObservabilityOfflineExperimentsItemsPayloadRetrieve).mockResolvedValue({
            id: detailItems[0].id,
            payload_state: 'not_provided',
            payload_expires_at: null,
            available: false,
            data: null,
        })
        jest.mocked(api.aiObservabilityOfflineExperimentsItemsResultsList).mockResolvedValue({
            count: 1,
            next_cursor: null,
            results: [result],
        })
        jest.mocked(api.aiObservabilityOfflineExperimentsResultsPayloadRetrieve).mockResolvedValue({
            id: result.id,
            payload_state: 'available',
            payload_expires_at: null,
            available: true,
            data: { error_message: 'The evaluator did not finish in time.' },
        })

        render(
            <OfflineItemInspector
                teamId={997}
                experimentId={detailExperiment.id}
                itemId={detailItems[0].id}
                resultId={result.id}
                scorerVersionId={result.scorer.id}
                onClose={jest.fn()}
                onSelectResult={jest.fn()}
            />
        )

        expect(await screen.findByText('The evaluator did not finish in time.')).toBeInTheDocument()
        expect(screen.getByText('Evaluator error: evaluator_timeout')).toBeInTheDocument()
    })

    it('hides stale results and disables Next after the next result page fails', async () => {
        const result = offlineDetailItemResults(detailItems[0].id)[0]
        jest.mocked(api.aiObservabilityOfflineExperimentsItemsRetrieve).mockResolvedValue(detailItems[0])
        jest.mocked(api.aiObservabilityOfflineExperimentsItemsPayloadRetrieve).mockResolvedValue({
            id: detailItems[0].id,
            payload_state: 'not_provided',
            payload_expires_at: null,
            available: false,
            data: null,
        })
        jest.mocked(api.aiObservabilityOfflineExperimentsItemsResultsList)
            .mockResolvedValueOnce({ count: 2, next_cursor: 'more', results: [result] })
            .mockRejectedValueOnce(
                new ApiError('Results unavailable', 503, undefined, { detail: 'Results unavailable' })
            )
        render(
            <OfflineItemInspector
                teamId={997}
                experimentId={detailExperiment.id}
                itemId={detailItems[0].id}
                onClose={jest.fn()}
                onSelectResult={jest.fn()}
            />
        )
        const label = `${result.scorer.name} v${result.scorer.version}`
        expect(await screen.findByText(label)).toBeInTheDocument()
        fireEvent.click(screen.getByText('Next'))
        expect(await screen.findByText('Results unavailable')).toBeInTheDocument()
        expect(screen.queryByText(label)).not.toBeInTheDocument()
        expect(screen.getByText('Next').closest('button')).toHaveAttribute('aria-disabled', 'true')
        fireEvent.click(screen.getByText('Next'))
        expect(api.aiObservabilityOfflineExperimentsItemsResultsList).toHaveBeenCalledTimes(2)
        expect(screen.getByText('Previous').closest('button')).not.toHaveAttribute('aria-disabled', 'true')
    })
})
