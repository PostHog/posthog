import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'

import { initKeaTests } from '~/test/init'

import * as api from '../generated/api'
import type { OfflineResultCellsApi } from '../generated/api.schemas'
import {
    detailExperiment,
    detailItems,
    makeOfflineDetailCells,
    makeOfflineDetailSummaries,
} from './offlineDetailFixtures'
import { offlineExperimentLogic } from './offlineExperimentLogic'
import { offlineCompletionError } from './offlineResultPresentation'

jest.mock('../generated/api', () => ({
    aiObservabilityOfflineExperimentsRetrieve: jest.fn(),
    aiObservabilityOfflineExperimentsScorerSummariesList: jest.fn(),
    aiObservabilityOfflineExperimentsItemsList: jest.fn(),
    aiObservabilityOfflineExperimentsResultCellsRetrieve: jest.fn(),
    aiObservabilityOfflineExperimentsCompleteCreate: jest.fn(),
}))

const readExperiment = jest.mocked(api.aiObservabilityOfflineExperimentsRetrieve)
const readSummaries = jest.mocked(api.aiObservabilityOfflineExperimentsScorerSummariesList)
const readItems = jest.mocked(api.aiObservabilityOfflineExperimentsItemsList)
const readCells = jest.mocked(api.aiObservabilityOfflineExperimentsResultCellsRetrieve)

describe('offlineExperimentLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
        readExperiment.mockResolvedValue(detailExperiment)
        readSummaries.mockResolvedValue({ count: 25, next_cursor: null, results: makeOfflineDetailSummaries(25) })
        readItems.mockResolvedValue({ count: 8, next_cursor: null, results: detailItems, scorer_versions: [] })
        readCells.mockImplementation(async (_team, _experiment, params) =>
            makeOfflineDetailCells(params.item_ids.split(','), params.scorer_version_ids.split(','))
        )
    })

    it('discovers every summary page and loads bounded score batches against fixed item IDs in the addressed environment', async () => {
        const summaries = makeOfflineDetailSummaries(101)
        readSummaries.mockImplementation(async (_team, _experiment, params) =>
            params?.cursor
                ? { count: 101, next_cursor: null, results: summaries.slice(100) }
                : { count: 101, next_cursor: 'more', results: summaries.slice(0, 100) }
        )
        const logic = offlineExperimentLogic({ teamId: 543, experimentId: detailExperiment.id })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.scorers).toHaveLength(101)
        expect(readExperiment).toHaveBeenCalledWith('543', detailExperiment.id)
        expect(readSummaries).toHaveBeenLastCalledWith('543', detailExperiment.id, { limit: 100, cursor: 'more' })
        expect(readCells).toHaveBeenCalledTimes(2)
        for (const [, , query] of readCells.mock.calls) {
            expect(query.item_ids.split(',')).toEqual(detailItems.map((item) => item.id).sort())
            expect(query.scorer_version_ids.split(',')).toHaveLength(20)
        }
        logic.actions.setViewport(180 * 100, 520)
        await expectLogic(logic).toFinishAllListeners()
        expect(
            readCells.mock.calls.some(([, , query]) => query.scorer_version_ids.includes(summaries[100].scorer.id))
        ).toBe(true)

        logic.actions.refresh()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.cellBatches[0]?.state).toBe('loaded')
    })

    it('does not replace cells for a new item page with a late response from the previous page', async () => {
        const logic = offlineExperimentLogic({ teamId: 997, experimentId: detailExperiment.id })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        let resolveOld: (value: OfflineResultCellsApi) => void = () => undefined
        readCells.mockImplementationOnce(
            () =>
                new Promise((resolve) => {
                    resolveOld = resolve
                })
        )
        logic.actions.refresh()
        await expectLogic(logic).toDispatchActions(['loadOfflineItemsSuccess', 'loadCellBatch'])
        const newItems = [detailItems[7]]
        readItems.mockResolvedValueOnce({ count: 8, next_cursor: null, results: newItems, scorer_versions: [] })
        logic.actions.nextItems('next-page')
        await expectLogic(logic).toDispatchActions(['loadOfflineItemsSuccess', 'loadedCellBatch'])
        resolveOld(
            makeOfflineDetailCells(
                [detailItems[0].id],
                makeOfflineDetailSummaries(20).map((summary) => summary.scorer.id)
            )
        )
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.items?.results).toEqual(newItems)
        expect(
            Object.values(logic.values.cellBatches)
                .flatMap((batch) => batch.response?.results || [])
                .every((cell) => cell.item_id === newItems[0].id)
        ).toBe(true)
    })

    it('discards a rejected item request after a newer item page succeeds', async () => {
        let rejectOld: (error: Error) => void = () => undefined
        readItems.mockImplementationOnce(
            () =>
                new Promise((_, reject) => {
                    rejectOld = reject
                })
        )
        const logic = offlineExperimentLogic({ teamId: 997, experimentId: detailExperiment.id })
        logic.mount()
        await expectLogic(logic, () => logic.actions.nextItems('newer-page')).toDispatchActions([
            'loadOfflineItemsSuccess',
        ])
        rejectOld(new ApiError('Old request failed', 503))
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.items?.results).toEqual(detailItems)
        expect(logic.values.itemsError).toBeNull()
    })

    it('keeps failed score batches distinct from missing cells and retries only the requested batch', async () => {
        readCells.mockRejectedValueOnce(new ApiError('Unavailable', 503))
        const logic = offlineExperimentLogic({ teamId: 997, experimentId: detailExperiment.id })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.cellBatches[0].state).toBe('error')
        expect(logic.values.cellBatches[1].state).toBe('loaded')
        const calls = readCells.mock.calls.length
        logic.actions.retryCellBatch(0)
        await expectLogic(logic).toFinishAllListeners()
        expect(readCells).toHaveBeenCalledTimes(calls + 1)
        expect(logic.values.cellBatches[0].state).toBe('loaded')
    })

    it.each([
        [1, 'Resume missing uploads'],
        [3, 'Uploading more cannot resolve this'],
    ])(
        'explains completion count mismatches without offering force completion (%s accepted)',
        (accepted, expectedMessage) => {
            expect(
                offlineCompletionError(
                    new ApiError('Conflict', 409, undefined, {
                        code: 'expected_count_mismatch',
                        detail: 'Counts differ',
                        expected_item_count: 2,
                        accepted_item_count: accepted,
                        expected_result_count: 2,
                        accepted_result_count: accepted,
                    })
                )
            ).toContain(expectedMessage)
        }
    )
})
