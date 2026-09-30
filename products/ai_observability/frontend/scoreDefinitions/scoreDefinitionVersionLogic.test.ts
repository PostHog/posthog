import { MOCK_DEFAULT_TEAM } from '~/lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { llmAnalyticsScoreDefinitionsNewVersionCreate, llmAnalyticsScoreDefinitionsRetrieve } from '../generated/api'
import type { ScoreDefinitionApi, ScoreDefinitionConfigApi } from '../generated/api.schemas'
import { scoreDefinitionVersionLogic } from './scoreDefinitionVersionLogic'

jest.mock('../generated/api', () => ({
    llmAnalyticsScoreDefinitionsRetrieve: jest.fn(),
    llmAnalyticsScoreDefinitionsNewVersionCreate: jest.fn(),
}))

const retrieve = jest.mocked(llmAnalyticsScoreDefinitionsRetrieve)
const createVersion = jest.mocked(llmAnalyticsScoreDefinitionsNewVersionCreate)
const definition: ScoreDefinitionApi = {
    id: 'scorer-1',
    name: 'Quality',
    description: '',
    kind: 'numeric',
    archived: false,
    current_version: 2,
    current_version_id: 'version-2',
    config: {},
    created_by: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: null,
    team: MOCK_DEFAULT_TEAM.id,
}

describe('scoreDefinitionVersionLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
    })

    it.each<ScoreDefinitionConfigApi>([
        { min: 0, max: null },
        { true_label: '', false_label: 'Needs work' },
        { options: [{ key: 'ok', label: 'Acceptable' }], selection_mode: 'multiple', min_selections: 0 },
    ])('preserves exact configuration when creating a version: %j', async (config) => {
        retrieve.mockResolvedValue({ ...definition, config })
        createVersion.mockResolvedValue({ ...definition, config, current_version: 3 })
        const onClose = jest.fn()
        const onSuccess = jest.fn()
        const logic = scoreDefinitionVersionLogic({
            teamId: String(MOCK_DEFAULT_TEAM.id),
            scorerId: definition.id,
            onClose,
            onSuccess,
        })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic, () => logic.actions.submit()).toFinishAllListeners()

        expect(createVersion).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), definition.id, {
            config,
            base_version: 2,
        })
        expect(onSuccess).toHaveBeenCalledWith(expect.objectContaining({ current_version: 3 }))
        expect(onClose).toHaveBeenCalledTimes(1)
    })

    it('requires another confirmation after a concurrent version change', async () => {
        retrieve
            .mockResolvedValueOnce(definition)
            .mockResolvedValueOnce({ ...definition, current_version: 3, config: { min: 0, max: 5 } })
        createVersion.mockRejectedValueOnce({ status: 409 })
        const onClose = jest.fn()
        const logic = scoreDefinitionVersionLogic({
            teamId: String(MOCK_DEFAULT_TEAM.id),
            scorerId: definition.id,
            onClose,
        })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic, () => logic.actions.submit()).toFinishAllListeners()

        expect(createVersion).toHaveBeenCalledTimes(1)
        expect(onClose).not.toHaveBeenCalled()
        expect(logic.values.currentDefinition?.current_version).toBe(3)
        expect(logic.values.error).toContain('confirm again')
        expect(logic.values.submitting).toBe(false)

        createVersion.mockResolvedValue({ ...definition, current_version: 4 })
        await expectLogic(logic, () => logic.actions.submit()).toFinishAllListeners()
        expect(createVersion).toHaveBeenLastCalledWith(String(MOCK_DEFAULT_TEAM.id), definition.id, {
            config: { min: 0, max: 5 },
            base_version: 3,
        })
    })

    it('ignores a second confirmation while the first request is pending', async () => {
        retrieve.mockResolvedValue(definition)
        let resolve: (value: ScoreDefinitionApi) => void = () => {}
        createVersion.mockImplementation(
            () =>
                new Promise((done) => {
                    resolve = done
                })
        )
        const logic = scoreDefinitionVersionLogic({
            teamId: String(MOCK_DEFAULT_TEAM.id),
            scorerId: definition.id,
            onClose: jest.fn(),
        })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.submit()
        logic.actions.submit()
        expect(createVersion).toHaveBeenCalledTimes(1)
        resolve({ ...definition, current_version: 3 })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.submitting).toBe(false)
    })
})
