import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { router } from 'kea-router'

import { ApiError } from 'lib/api-error'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import * as api from '../generated/api'
import type { OfflineResultReadApi } from '../generated/api.schemas'
import { traceDrawerLogic } from '../redesign/trace/traceDrawerLogic'
import { detailExperiment, detailItems, offlineDetailItemResults } from './offlineDetailFixtures'
import { OfflineItemInspector } from './OfflineItemInspector'

jest.mock('../generated/api', () => ({
    aiObservabilityTracesAvailabilityCreate: jest.fn(),
    aiObservabilityOfflineExperimentsItemsRetrieve: jest.fn(),
    aiObservabilityOfflineExperimentsItemsPayloadRetrieve: jest.fn(),
    aiObservabilityOfflineExperimentsItemsResultsList: jest.fn(),
    aiObservabilityOfflineExperimentsResultsPayloadRetrieve: jest.fn(),
}))

describe('OfflineItemInspector', () => {
    afterEach(cleanup)
    beforeEach(() => {
        initKeaTests()
        localStorage.clear()
        jest.clearAllMocks()
        jest.mocked(api.aiObservabilityOfflineExperimentsItemsRetrieve).mockReset()
        jest.mocked(api.aiObservabilityOfflineExperimentsItemsPayloadRetrieve).mockReset()
        jest.mocked(api.aiObservabilityOfflineExperimentsItemsResultsList).mockReset()
        jest.mocked(api.aiObservabilityOfflineExperimentsResultsPayloadRetrieve).mockReset()
    })

    it.each(['Application trace', 'Evaluator trace'])(
        'opens %s in the drawer and restores the selected result when closed',
        async (label) => {
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.AI_OBSERVABILITY_TRACE_REDESIGN], {
                [FEATURE_FLAGS.AI_OBSERVABILITY_TRACE_REDESIGN]: true,
            })
            const result = { ...offlineDetailItemResults(detailItems[0].id)[0], evaluator_trace_id: 'judge-trace' }
            const item = { ...detailItems[0], application_trace_id: 'app-trace' }
            const path = `/project/997${urls.aiObservabilityOfflineEvaluationExperiment(detailExperiment.id)}`
            const selection = { item_id: item.id, result_id: result.id, scorer_version_id: result.scorer.id }
            router.actions.push(path, selection)
            jest.mocked(api.aiObservabilityOfflineExperimentsItemsRetrieve).mockResolvedValue(item)
            jest.mocked(api.aiObservabilityOfflineExperimentsItemsPayloadRetrieve).mockResolvedValue({
                id: item.id,
                payload_state: 'not_provided',
                payload_expires_at: null,
                available: false,
                data: null,
            })
            jest.mocked(api.aiObservabilityOfflineExperimentsItemsResultsList).mockResolvedValue({
                count: 1,
                next: null,
                previous: null,
                next_cursor: null,
                results: [result],
            })
            jest.mocked(api.aiObservabilityOfflineExperimentsResultsPayloadRetrieve).mockResolvedValue({
                id: result.id,
                payload_state: 'available',
                payload_expires_at: null,
                available: true,
                data: { reasoning: 'The answer matches the reference.' },
            })
            const onClose = jest.fn()
            let confirmTraces!: (response: { available_trace_ids: string[] }) => void
            jest.mocked(api.aiObservabilityTracesAvailabilityCreate).mockReturnValue(
                new Promise((resolve) => {
                    confirmTraces = resolve
                })
            )
            render(
                <OfflineItemInspector
                    teamId={997}
                    experimentId={detailExperiment.id}
                    itemId={item.id}
                    resultId={result.id}
                    scorerVersionId={result.scorer.id}
                    onClose={onClose}
                    onSelectResult={jest.fn()}
                />
            )
            await screen.findByText('The answer matches the reference.')
            expect(screen.queryByText('Application trace', { selector: 'a *' })).not.toBeInTheDocument()
            expect(screen.queryByText('Evaluator trace', { selector: 'a *' })).not.toBeInTheDocument()
            await act(async () => confirmTraces({ available_trace_ids: ['app-trace', 'judge-trace'] }))
            const link = (await screen.findByText(label, { selector: 'a *' })).closest('a')!
            expect(screen.getByText('Result metadata').closest('details')).not.toHaveAttribute('open')
            const traceId = label === 'Application trace' ? 'app-trace' : 'judge-trace'
            expect(link).toHaveAttribute('href', `/project/997${urls.aiObservabilityTrace(traceId)}`)
            const drawer = traceDrawerLogic({ listId: 'offline-experiment' })

            fireEvent.click(link, { ctrlKey: true })
            expect(drawer.values.openTraceId).toBeNull()
            fireEvent.click(link)

            expect(drawer.values.openTraceId).toBe(traceId)
            expect(router.values.location.pathname).toBe(path)
            expect(router.values.searchParams).toMatchObject(selection)
            await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
            expect(onClose).not.toHaveBeenCalled()

            act(() => drawer.actions.close())
            expect(await screen.findByRole('dialog')).toBeInTheDocument()
            expect(screen.getByText('The answer matches the reference.')).toBeInTheDocument()
            expect(router.values.searchParams).toEqual(selection)
        }
    )

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
            next: null,
            previous: null,
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
            .mockResolvedValueOnce({ count: 2, next: null, previous: null, next_cursor: 'more', results: [result] })
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
        expect(await screen.findByText(result.scorer.name, { selector: 'button span' })).toBeInTheDocument()
        fireEvent.click(screen.getByText('Next'))
        expect(await screen.findByText('Results unavailable')).toBeInTheDocument()
        expect(screen.queryByText(result.scorer.name, { selector: 'button span' })).not.toBeInTheDocument()
        expect(screen.getByText('Next').closest('button')).toHaveAttribute('aria-disabled', 'true')
        fireEvent.click(screen.getByText('Next'))
        expect(api.aiObservabilityOfflineExperimentsItemsResultsList).toHaveBeenCalledTimes(2)
        expect(screen.getByText('Previous').closest('button')).not.toHaveAttribute('aria-disabled', 'true')
    })
})
