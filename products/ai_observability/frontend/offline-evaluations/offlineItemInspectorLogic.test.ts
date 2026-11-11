import { waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import * as api from '../generated/api'
import { detailExperiment, detailItems, offlineDetailItemResults } from './offlineDetailFixtures'
import { offlineItemInspectorLogic } from './offlineItemInspectorLogic'

jest.mock('../generated/api', () => ({
    aiObservabilityTracesAvailabilityCreate: jest.fn(),
    aiObservabilityOfflineExperimentsItemsRetrieve: jest.fn(),
    aiObservabilityOfflineExperimentsItemsPayloadRetrieve: jest.fn(),
    aiObservabilityOfflineExperimentsItemsResultsList: jest.fn(),
    aiObservabilityOfflineExperimentsResultsPayloadRetrieve: jest.fn(),
}))

describe('offlineItemInspectorLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
        jest.mocked(api.aiObservabilityTracesAvailabilityCreate).mockResolvedValue({ available_trace_ids: [] })
        jest.mocked(api.aiObservabilityOfflineExperimentsItemsRetrieve).mockResolvedValue(detailItems[0])
        jest.mocked(api.aiObservabilityOfflineExperimentsItemsPayloadRetrieve).mockResolvedValue({
            id: detailItems[0].id,
            payload_state: 'available',
            payload_expires_at: null,
            available: true,
            data: { input: false, output: '', expected_output: null },
        })
        jest.mocked(api.aiObservabilityOfflineExperimentsItemsResultsList).mockImplementation(
            async (_team, _experiment, _item, params) => {
                const all = offlineDetailItemResults(detailItems[0].id)
                return {
                    count: params?.scorer_version_ids ? 1 : all.length,
                    next: null,
                    previous: null,
                    next_cursor: params?.scorer_version_ids ? null : 'more',
                    results: params?.scorer_version_ids
                        ? all.filter((result) => result.scorer.id === params.scorer_version_ids)
                        : all.slice(0, 20),
                }
            }
        )
        jest.mocked(api.aiObservabilityOfflineExperimentsResultsPayloadRetrieve).mockImplementation(
            async (_team, _experiment, resultId) => ({
                id: resultId,
                payload_state: 'expired',
                payload_expires_at: null,
                available: false,
                data: null,
            })
        )
    })

    it('opens a linked result beyond the first result page using its exact version and fetches only its payload', async () => {
        const selected = offlineDetailItemResults(detailItems[0].id)[24]
        const logic = offlineItemInspectorLogic({
            teamId: 543,
            experimentId: detailExperiment.id,
            itemId: detailItems[0].id,
            resultId: selected.id,
            scorerVersionId: selected.scorer.id,
        })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.results?.results).toHaveLength(20)
        expect(logic.values.selectedResult?.id).toBe(selected.id)
        expect(api.aiObservabilityOfflineExperimentsItemsResultsList).toHaveBeenCalledWith(
            '543',
            detailExperiment.id,
            detailItems[0].id,
            { limit: 1, scorer_version_ids: selected.scorer.id }
        )
        expect(api.aiObservabilityOfflineExperimentsResultsPayloadRetrieve).toHaveBeenCalledTimes(1)
        expect(api.aiObservabilityOfflineExperimentsResultsPayloadRetrieve).toHaveBeenCalledWith(
            '543',
            detailExperiment.id,
            selected.id
        )
        expect(logic.values.itemPayload?.data).toEqual({ input: false, output: '', expected_output: null })
        expect(logic.values.resultPayload).toMatchObject({ available: false, payload_state: 'expired' })
    })

    it('does not request reasoning payloads when opening only an item', async () => {
        const logic = offlineItemInspectorLogic({
            teamId: 997,
            experimentId: detailExperiment.id,
            itemId: detailItems[0].id,
        })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(api.aiObservabilityOfflineExperimentsResultsPayloadRetrieve).not.toHaveBeenCalled()
        expect(logic.values.selectedResult).toBeNull()
        expect(api.aiObservabilityTracesAvailabilityCreate).not.toHaveBeenCalled()
    })

    it.each([{ found: ['app-trace'] }, { found: [] }, { found: null }])(
        'shows only confirmed trace IDs: $found',
        async ({ found }) => {
            const selected = { ...offlineDetailItemResults(detailItems[0].id)[0], evaluator_trace_id: 'judge-trace' }
            jest.mocked(api.aiObservabilityOfflineExperimentsItemsRetrieve).mockResolvedValue({
                ...detailItems[0],
                application_trace_id: 'app-trace',
            })
            jest.mocked(api.aiObservabilityOfflineExperimentsItemsResultsList).mockResolvedValue({
                count: 1,
                next: null,
                previous: null,
                next_cursor: null,
                results: [selected],
            })
            if (found === null) {
                jest.mocked(api.aiObservabilityTracesAvailabilityCreate).mockRejectedValue(
                    new Error('Query unavailable')
                )
            } else {
                jest.mocked(api.aiObservabilityTracesAvailabilityCreate).mockResolvedValue({
                    available_trace_ids: found,
                })
            }
            const logic = offlineItemInspectorLogic({
                teamId: 997,
                experimentId: detailExperiment.id,
                itemId: detailItems[0].id,
                resultId: selected.id,
                scorerVersionId: selected.scorer.id,
            })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.availableTraceIds).toEqual(found ?? [])
            expect(api.aiObservabilityTracesAvailabilityCreate).toHaveBeenCalledTimes(1)
            expect(api.aiObservabilityTracesAvailabilityCreate).toHaveBeenCalledWith(
                '997',
                { trace_ids: ['app-trace', 'judge-trace'] },
                { signal: expect.any(AbortSignal) }
            )
            expect(logic.values.item?.id).toBe(detailItems[0].id)
            expect(logic.values.selectedResult?.id).toBe(selected.id)
            jest.mocked(api.aiObservabilityTracesAvailabilityCreate).mockRejectedValue(new Error('Query unavailable'))
            logic.actions.refreshItem()
            expect(logic.values.availableTraceIds).toEqual([])
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.availableTraceIds).toEqual([])
        }
    )

    it('cancels superseded lookups, ignores their responses, and cancels on close', async () => {
        const results = offlineDetailItemResults(detailItems[0].id)
            .slice(0, 2)
            .map((result, index) => ({
                ...result,
                evaluator_trace_id: `judge-${index}`,
            }))
        jest.mocked(api.aiObservabilityOfflineExperimentsItemsRetrieve).mockResolvedValue({
            ...detailItems[0],
            application_trace_id: 'app-trace',
        })
        jest.mocked(api.aiObservabilityOfflineExperimentsItemsResultsList).mockResolvedValue({
            count: results.length,
            next: null,
            previous: null,
            next_cursor: null,
            results,
        })
        const requests: {
            signal: AbortSignal
            resolve: (response: { available_trace_ids: string[] }) => void
        }[] = []
        jest.mocked(api.aiObservabilityTracesAvailabilityCreate).mockImplementation(
            (_team, _body, options) => new Promise((resolve) => requests.push({ signal: options!.signal!, resolve }))
        )
        const props = {
            teamId: 997,
            experimentId: detailExperiment.id,
            itemId: detailItems[0].id,
            resultId: results[0].id,
            scorerVersionId: results[0].scorer.id,
        }
        const logic = offlineItemInspectorLogic(props)
        const unmount = logic.mount()
        await waitFor(() => expect(requests).toHaveLength(1))

        offlineItemInspectorLogic({ ...props, resultId: results[1].id, scorerVersionId: results[1].scorer.id })
        expect(requests[0].signal.aborted).toBe(true)
        await waitFor(() => expect(requests).toHaveLength(2))
        requests[1].resolve({ available_trace_ids: ['app-trace', 'judge-1'] })
        await waitFor(() => expect(logic.values.availableTraceIds).toEqual(['app-trace', 'judge-1']))
        requests[0].resolve({ available_trace_ids: ['app-trace', 'judge-0'] })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.availableTraceIds).toEqual(['app-trace', 'judge-1'])

        logic.actions.loadOfflineItemResults()
        await expectLogic(logic).toFinishAllListeners()
        expect(requests).toHaveLength(2)

        logic.actions.refreshItem()
        expect(logic.values.availableTraceIds).toEqual([])
        await waitFor(() => expect(requests).toHaveLength(3))
        unmount()
        expect(requests[2].signal.aborted).toBe(true)
        requests[2].resolve({ available_trace_ids: ['app-trace', 'judge-1'] })
    })

    it('does not reuse the previous evaluator trace when the new result fails to load', async () => {
        const selected = { ...offlineDetailItemResults(detailItems[0].id)[0], evaluator_trace_id: 'old-judge' }
        jest.mocked(api.aiObservabilityOfflineExperimentsItemsRetrieve).mockResolvedValue({
            ...detailItems[0],
            application_trace_id: 'app-trace',
        })
        jest.mocked(api.aiObservabilityOfflineExperimentsItemsResultsList).mockResolvedValue({
            count: 1,
            next: null,
            previous: null,
            next_cursor: null,
            results: [selected],
        })
        jest.mocked(api.aiObservabilityTracesAvailabilityCreate).mockImplementation(async (_team, body) => ({
            available_trace_ids: body.trace_ids,
        }))
        const props = {
            teamId: 997,
            experimentId: detailExperiment.id,
            itemId: detailItems[0].id,
            resultId: selected.id,
            scorerVersionId: selected.scorer.id,
        }
        const logic = offlineItemInspectorLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.availableTraceIds).toEqual(['app-trace', 'old-judge'])

        jest.mocked(api.aiObservabilityOfflineExperimentsItemsResultsList).mockRejectedValueOnce(
            new Error('Unavailable')
        )
        offlineItemInspectorLogic({ ...props, resultId: 'missing-result' })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.selectedResult).toBeNull()
        expect(logic.values.availableTraceIds).toEqual(['app-trace'])
    })
})
