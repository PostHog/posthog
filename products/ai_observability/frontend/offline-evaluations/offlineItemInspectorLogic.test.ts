import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import * as api from '../generated/api'
import { detailExperiment, detailItems, offlineDetailItemResults } from './offlineDetailFixtures'
import { offlineItemInspectorLogic } from './offlineItemInspectorLogic'

jest.mock('../generated/api', () => ({
    aiObservabilityOfflineExperimentsItemsRetrieve: jest.fn(),
    aiObservabilityOfflineExperimentsItemsPayloadRetrieve: jest.fn(),
    aiObservabilityOfflineExperimentsItemsResultsList: jest.fn(),
    aiObservabilityOfflineExperimentsResultsPayloadRetrieve: jest.fn(),
}))

describe('offlineItemInspectorLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
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
    })
})
