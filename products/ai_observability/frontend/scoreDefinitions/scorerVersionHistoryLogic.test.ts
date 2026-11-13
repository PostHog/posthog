import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import * as api from '../generated/api'
import type { ScoreDefinitionVersionApi, ScoreDefinitionVersionPageApi } from '../generated/api.schemas'
import { historyDefinition, historyVersions } from './scorerVersionHistory.fixtures'
import { scorerVersionHistoryLogic } from './scorerVersionHistoryLogic'

jest.mock('../generated/api', () => ({ llmAnalyticsScoreDefinitionsVersionsList: jest.fn() }))

const versions = jest.mocked(api.llmAnalyticsScoreDefinitionsVersionsList)
const page = (results: ScoreDefinitionVersionApi[], cursor: string | null = null): ScoreDefinitionVersionPageApi => ({
    count: 2,
    results,
    next_cursor: cursor,
    next: cursor,
    previous: null,
})

describe('scorer version history', () => {
    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
    })

    it('uses the selected saved configuration and keeps it selected when older pages fail or arrive', async () => {
        versions.mockResolvedValueOnce(page([historyVersions[0]], 'older'))
        const logic = scorerVersionHistoryLogic({ definition: historyDefinition })
        logic.mount()
        expect(versions).not.toHaveBeenCalled()
        await expectLogic(logic, () => logic.actions.openHistory()).toFinishAllListeners()
        expect(logic.values.versionDraft?.numericPassingThreshold).toBe('8')
        logic.actions.selectVersion('quality-v2')

        versions.mockRejectedValueOnce(new Error('Unavailable'))
        await expectLogic(logic, () => logic.actions.loadVersions('older')).toFinishAllListeners()
        expect(logic.values.history.error).toBe('Could not load scorer versions.')
        expect(logic.values.historyLoading).toBe(false)
        expect(logic.values.selectedVersion?.id).toBe('quality-v2')

        versions.mockResolvedValueOnce(page([historyVersions[1]]))
        await expectLogic(logic, () =>
            logic.actions.loadVersions(logic.values.cursor ?? undefined)
        ).toFinishAllListeners()
        expect(logic.values.history.error).toBeNull()
        expect(logic.values.history.results).toEqual(historyVersions)
        expect(logic.values.selectedVersion?.id).toBe('quality-v2')

        logic.actions.selectVersion('quality-v1')
        expect(logic.values.versionDraft?.numericPassingThreshold).toBe('7')
        expect(logic.values.versionDraft?.numericStep).toBe('1')
        expect(historyDefinition.config).toEqual(historyVersions[0].config)
        logic.actions.closeHistory()
        expect(logic.values.isOpen).toBe(false)
    })

    it('displays the historical composite formula and input pins instead of the current ones', async () => {
        const previous = {
            ...historyVersions[1],
            calculation: 'composite' as const,
            composition: { expression: 'quality * 2', inputs: [{ alias: 'quality', scorer_version_id: 'source-v1' }] },
        }
        const definition = {
            ...historyDefinition,
            calculation: 'composite' as const,
            composition: { expression: 'quality * 3', inputs: [{ alias: 'quality', scorer_version_id: 'source-v2' }] },
        }
        versions.mockResolvedValueOnce(page([previous]))
        const logic = scorerVersionHistoryLogic({ definition })
        logic.mount()
        await expectLogic(logic, () => logic.actions.openHistory()).toFinishAllListeners()
        expect(logic.values.versionDraft?.expression).toBe('quality * 2')
        expect(logic.values.selectedVersion?.composition?.inputs).toEqual(previous.composition.inputs)
        expect(logic.values.versionDraft?.inputs).toEqual([])
        expect(definition.composition.expression).toBe('quality * 3')
    })
})
