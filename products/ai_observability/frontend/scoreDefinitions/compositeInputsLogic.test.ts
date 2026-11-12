import { MOCK_DEFAULT_TEAM } from '~/lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import {
    llmAnalyticsScoreDefinitionsList,
    llmAnalyticsScoreDefinitionsVersionsList,
    llmAnalyticsScoreDefinitionsValidateCompositionCreate,
} from '../generated/api'
import { compositeInputsLogic } from './compositeInputsLogic'
import {
    buildCompositionFromDraft,
    buildConfigFromDraft,
    createDraft,
    type ScoreDefinitionDraft,
} from './scoreDefinitionModalUtils'

jest.mock('../generated/api', () => ({
    llmAnalyticsScoreDefinitionsList: jest.fn(),
    llmAnalyticsScoreDefinitionsVersionsList: jest.fn(),
    llmAnalyticsScoreDefinitionsValidateCompositionCreate: jest.fn(),
}))

const list = jest.mocked(llmAnalyticsScoreDefinitionsList)
const versions = jest.mocked(llmAnalyticsScoreDefinitionsVersionsList)
const validate = jest.mocked(llmAnalyticsScoreDefinitionsValidateCompositionCreate)
const emptyPage = { count: 0, results: [], next: null, previous: null, next_cursor: null }

describe('composite input selection', () => {
    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
        list.mockResolvedValue(emptyPage)
        versions.mockResolvedValue(emptyPage)
    })

    it('loads existing input versions automatically and retains other inputs when a refresh fails', async () => {
        const logic = compositeInputsLogic({ id: 'editor', initialDefinitionIds: ['quality', 'safety'] })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(versions).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), 'quality', { limit: 50 })
        expect(versions).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), 'safety', { limit: 50 })
        expect(Object.keys(logic.values.versions).sort()).toEqual(['quality', 'safety'])

        versions.mockRejectedValueOnce(new Error('Unavailable'))
        await expectLogic(logic, () => logic.actions.loadVersions('quality')).toFinishAllListeners()
        expect(logic.values.versionsLoadingById.quality).toBe(false)
        expect(Object.keys(logic.values.versions).sort()).toEqual(['quality', 'safety'])
        expect(logic.values.versionsError).toBe('Unavailable')
    })

    it('combines tag filters with the input search and excludes composite sources', async () => {
        const logic = compositeInputsLogic({ id: 'editor' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(logic, () => {
            logic.actions.setTagFilters({ tags: ['support', 'safety'], tag_match: 'all' })
            logic.actions.setSearch('accuracy')
        }).toFinishAllListeners()
        expect(list).toHaveBeenLastCalledWith(
            String(MOCK_DEFAULT_TEAM.id),
            expect.objectContaining({
                calculation: 'reported',
                search: 'accuracy',
                tags: '["support","safety"]',
                tag_match: 'all',
                limit: 50,
            })
        )
    })

    it('ties validation results to the checked formula and preserves server errors', async () => {
        const logic = compositeInputsLogic({ id: 'editor' })
        logic.mount()
        const draft: ScoreDefinitionDraft = {
            ...createDraft('create'),
            calculation: 'composite',
            kind: 'boolean',
            expression: 'safe',
            inputs: [
                {
                    alias: 'safe',
                    definition_id: 'safe',
                    scorer_version_id: 'safe-v1',
                    name: 'Safety',
                    kind: 'boolean',
                    version: 1,
                    latest_version: 1,
                    latest_version_id: 'safe-v1',
                    config: {},
                },
            ],
        }
        const body = {
            kind: draft.kind,
            composition: buildCompositionFromDraft(draft),
            config: buildConfigFromDraft(draft),
        }
        validate.mockResolvedValue({ valid: true })
        await expectLogic(logic, () => logic.actions.validateFormula(draft)).toFinishAllListeners()
        expect(validate).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), body)
        expect(logic.values.validation).toEqual({ fingerprint: JSON.stringify(body), error: null })

        validate.mockRejectedValue({ detail: 'Unknown input: missing' })
        await expectLogic(logic, () =>
            logic.actions.validateFormula({ ...draft, expression: 'missing' })
        ).toFinishAllListeners()
        expect(logic.values.validation?.error).toBe('Unknown input: missing')
        expect(logic.values.validation?.fingerprint).not.toBe(JSON.stringify(body))
    })
})
