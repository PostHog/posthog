import { MOCK_DEFAULT_TEAM } from '~/lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import {
    llmAnalyticsScoreDefinitionsCreate,
    llmAnalyticsScoreDefinitionsNewVersionCreate,
    llmAnalyticsScoreDefinitionsPartialUpdate,
    llmAnalyticsScoreDefinitionsRetrieve,
} from '../generated/api'
import type { ScoreDefinitionApi, ScoreDefinitionConfigApi } from '../generated/api.schemas'
import { scorerLogic } from './scorerLogic'

jest.mock('../generated/api', () => ({
    llmAnalyticsScoreDefinitionsCreate: jest.fn(),
    llmAnalyticsScoreDefinitionsNewVersionCreate: jest.fn(),
    llmAnalyticsScoreDefinitionsPartialUpdate: jest.fn(),
    llmAnalyticsScoreDefinitionsRetrieve: jest.fn(),
}))

const retrieve = jest.mocked(llmAnalyticsScoreDefinitionsRetrieve)
const create = jest.mocked(llmAnalyticsScoreDefinitionsCreate)
const createVersion = jest.mocked(llmAnalyticsScoreDefinitionsNewVersionCreate)
const update = jest.mocked(llmAnalyticsScoreDefinitionsPartialUpdate)
const definition: ScoreDefinitionApi = {
    id: 'scorer-example',
    name: 'Answer quality',
    description: '',
    kind: 'numeric',
    config: {},
    archived: false,
    current_version: 2,
    current_version_id: 'version-example',
    team: MOCK_DEFAULT_TEAM.id,
    created_by: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: null,
}

describe('scorer editor', () => {
    beforeEach(() => {
        initKeaTests()
        window.POSTHOG_APP_CONTEXT!.resource_access_control = {
            ...window.POSTHOG_APP_CONTEXT!.resource_access_control,
            llm_analytics: AccessControlLevel.Editor,
        }
        jest.resetAllMocks()
        retrieve.mockResolvedValue(definition)
    })

    it.each<{ kind: ScoreDefinitionApi['kind']; config: ScoreDefinitionConfigApi; duplicateFrom?: string }>([
        { kind: 'numeric', config: { min: 0, max: null, passing_rule: null } },
        { kind: 'numeric', config: {}, duplicateFrom: 'another-scorer' },
        { kind: 'boolean', config: { true_label: '', false_label: 'Needs work', true_is_failure: false } },
        { kind: 'categorical', config: { options: [{ key: 'good', label: 'Good' }], selection_mode: 'single' } },
    ])(
        'saves only metadata when an existing $kind configuration is untouched',
        async ({ kind, config, duplicateFrom }) => {
            const existing = { ...definition, kind, config }
            retrieve.mockResolvedValue(existing)
            update.mockResolvedValue({ ...existing, name: 'Renamed scorer' })
            const logic = scorerLogic({ scorerId: definition.id, duplicateFrom })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            expect(retrieve).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), definition.id)
            expect(logic.values.draft.name).toBe(existing.name)
            expect(logic.values.hasChanges).toBe(false)
            expect(logic.values.hasUnsavedChanges).toBe(false)
            expect(logic.values.willCreateVersion).toBe(false)
            logic.actions.setDraftField('name', 'Renamed scorer')
            expect(logic.values.hasUnsavedChanges).toBe(true)
            expect(logic.values.willCreateVersion).toBe(false)
            logic.actions.setDraftField('name', existing.name)
            expect(logic.values.hasUnsavedChanges).toBe(false)
            logic.actions.setDraftField('name', 'Renamed scorer')
            await expectLogic(logic, () => logic.actions.save()).toFinishAllListeners()

            expect(update).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), definition.id, {
                name: 'Renamed scorer',
                description: '',
            })
            expect(createVersion).not.toHaveBeenCalled()
            expect(logic.values.definition?.config).toEqual(config)
            expect(logic.values.hasChanges).toBe(false)
            expect(logic.values.hasUnsavedChanges).toBe(false)
        }
    )

    it('saves metadata and passing rules together in a version guarded by the original version number', async () => {
        createVersion.mockResolvedValue({
            ...definition,
            name: 'Updated quality',
            current_version: 3,
            config: { passing_rule: { operator: 'gte', threshold: 7 } },
        })
        const logic = scorerLogic({ scorerId: definition.id })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setDraftField('name', 'Updated quality')
        logic.actions.setDraftField('numericPassingEnabled', true)
        logic.actions.setDraftField('numericPassingThreshold', '7')
        expect(logic.values.willCreateVersion).toBe(true)

        await expectLogic(logic, () => logic.actions.save()).toFinishAllListeners()

        expect(createVersion).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), definition.id, {
            name: 'Updated quality',
            description: '',
            config: { passing_rule: { operator: 'gte', threshold: 7 } },
            base_version: 2,
        })
        expect(update).not.toHaveBeenCalled()
        expect(logic.values.definition?.current_version).toBe(3)
        expect(logic.values.hasChanges).toBe(false)
        expect(logic.values.willCreateVersion).toBe(false)
    })

    it.each([{}, { true_is_failure: null }])(
        'persists the default boolean polarity on metadata save without marking the initial draft dirty: %j',
        async (polarityConfig) => {
            const existing: ScoreDefinitionApi = {
                ...definition,
                kind: 'boolean',
                config: { true_label: '', false_label: 'Needs work', ...polarityConfig },
            }
            const saved = {
                ...existing,
                name: 'Renamed scorer',
                current_version: 3,
                config: { false_label: 'Needs work', true_is_failure: false },
            }
            retrieve.mockResolvedValue(existing)
            createVersion.mockResolvedValue(saved)
            const logic = scorerLogic({ scorerId: definition.id })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.draft.booleanPassing).toBe('true')
            expect(logic.values.configChanged).toBe(false)
            expect(logic.values.hasChanges).toBe(false)
            expect(logic.values.hasUnsavedChanges).toBe(false)
            expect(logic.values.willCreateVersion).toBe(false)
            expect(createVersion).not.toHaveBeenCalled()
            logic.actions.setDraftField('name', 'Renamed scorer')
            expect(logic.values.willCreateVersion).toBe(true)
            await expectLogic(logic, () => logic.actions.save()).toFinishAllListeners()

            expect(createVersion).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), definition.id, {
                name: 'Renamed scorer',
                description: '',
                config: saved.config,
                base_version: 2,
            })
            expect(update).not.toHaveBeenCalled()
            expect(logic.values.hasChanges).toBe(false)
            expect(logic.values.hasUnsavedChanges).toBe(false)
            expect(logic.values.willCreateVersion).toBe(false)
        }
    )

    it('duplicates a scorer with its boolean polarity without updating the source', async () => {
        const existing: ScoreDefinitionApi = {
            ...definition,
            kind: 'boolean',
            config: { true_label: 'Flagged', false_label: 'Clear', true_is_failure: true },
        }
        retrieve.mockResolvedValue(existing)
        create.mockResolvedValue({
            ...existing,
            id: 'duplicate-example',
            name: 'Answer quality copy',
            current_version: 1,
        })
        const logic = scorerLogic({ scorerId: 'new', duplicateFrom: definition.id })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.hasUnsavedChanges).toBe(false)
        logic.actions.setDraftField('description', 'Changed description')
        expect(logic.values.hasUnsavedChanges).toBe(true)
        logic.actions.setDraftField('description', '')
        expect(logic.values.hasUnsavedChanges).toBe(false)
        await expectLogic(logic, () => logic.actions.save()).toFinishAllListeners()

        expect(create).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            name: 'Answer quality copy',
            description: '',
            kind: 'boolean',
            config: existing.config,
        })
        expect(update).not.toHaveBeenCalled()
        expect(createVersion).not.toHaveBeenCalled()
    })

    it('ignores a repeated save while the version request is pending', async () => {
        let resolve: (value: ScoreDefinitionApi) => void = () => {}
        createVersion.mockImplementation(
            () =>
                new Promise((done) => {
                    resolve = done
                })
        )
        const logic = scorerLogic({ scorerId: definition.id })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setDraftField('numericMax', '10')

        logic.actions.save()
        logic.actions.save()

        expect(createVersion).toHaveBeenCalledTimes(1)
        expect(logic.values.saving).toBe(true)
        resolve({ ...definition, config: { max: 10 }, current_version: 3 })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.saving).toBe(false)
    })

    it('keeps edits after a version conflict without retrying against a newer version', async () => {
        createVersion.mockRejectedValue({ status: 409 })
        const logic = scorerLogic({ scorerId: definition.id })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setDraftField('numericMax', '10')

        await expectLogic(logic, () => logic.actions.save()).toFinishAllListeners()

        expect(createVersion).toHaveBeenCalledTimes(1)
        expect(logic.values.error).toContain('newer version')
        expect(logic.values.draft.numericMax).toBe('10')
        expect(logic.values.definition?.current_version).toBe(2)
        expect(logic.values.hasChanges).toBe(true)
        expect(logic.values.hasUnsavedChanges).toBe(true)
        expect(logic.values.saving).toBe(false)
    })

    it.each<{
        kind: ScoreDefinitionApi['kind']
        config: ScoreDefinitionConfigApi
        expectedConfig: ScoreDefinitionConfigApi
    }>([
        {
            kind: 'numeric',
            config: { min: 0, max: null, passing_rule: null },
            expectedConfig: { min: 0, max: null, passing_rule: null },
        },
        { kind: 'boolean', config: {}, expectedConfig: { true_is_failure: false } },
        {
            kind: 'boolean',
            config: { true_label: '', false_label: 'Needs work', true_is_failure: null },
            expectedConfig: { false_label: 'Needs work', true_is_failure: false },
        },
        {
            kind: 'boolean',
            config: { true_label: 'Detected', false_label: ' ', true_is_failure: true },
            expectedConfig: { true_label: 'Detected', true_is_failure: true },
        },
    ])('creates an unchanged $kind version with explicit defaults', async ({ kind, config, expectedConfig }) => {
        retrieve.mockResolvedValue({ ...definition, kind, config })
        createVersion.mockResolvedValue({ ...definition, kind, config: expectedConfig, current_version: 3 })
        const logic = scorerLogic({ scorerId: definition.id })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic, () => logic.actions.createVersion()).toFinishAllListeners()

        expect(createVersion).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), definition.id, {
            config: expectedConfig,
            base_version: 2,
        })
        expect(logic.values.hasChanges).toBe(false)
    })
})
