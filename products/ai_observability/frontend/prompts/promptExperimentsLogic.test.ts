import { MOCK_DEFAULT_TEAM } from '~/lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { experimentsList } from '../../../experiments/frontend/generated/api'
import { createPromptExperimentModalLogic } from './createPromptExperimentModalLogic'
import { promptExperimentsLogic } from './promptExperimentsLogic'

jest.mock('../../../experiments/frontend/generated/api', () => ({
    experimentsList: jest.fn(),
    experimentsCreateFromPromptCreate: jest.fn(),
    experimentsPromptTemplatesRetrieve: jest.fn(),
}))

const mockExperimentsList = experimentsList as jest.MockedFunction<typeof experimentsList>

const PROMPT_NAME = 'my-prompt'

const baseExperiment = {
    id: 1,
    name: 'My exp',
    description: null,
    feature_flag_key: 'my-exp',
    feature_flag: {} as any,
    holdout: {} as any,
    exposure_cohort: null,
    saved_metrics: [],
    archived: false,
    deleted: false,
    created_by: { id: 1 } as any,
    created_at: '2025-01-15T00:00:00Z',
    updated_at: '2025-01-15T00:00:00Z',
}

describe('promptExperimentsLogic', () => {
    let logic: ReturnType<typeof promptExperimentsLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
        mockExperimentsList.mockResolvedValue({
            count: 1,
            next: null,
            previous: null,
            results: [{ ...baseExperiment } as any],
        })

        logic = promptExperimentsLogic({ promptName: PROMPT_NAME })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('loads experiments on mount filtered by prompt_name', async () => {
        await expectLogic(logic).toFinishAllListeners()
        expect(mockExperimentsList).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            prompt_name: PROMPT_NAME,
            order: '-created_at',
        })
        await expectLogic(logic).toMatchValues({
            experiments: [expect.objectContaining({ id: 1, name: 'My exp' })],
        })
    })

    it('reloads experiments when modal reports submitCreateSuccess', async () => {
        await expectLogic(logic).toFinishAllListeners()
        expect(mockExperimentsList).toHaveBeenCalledTimes(1)

        const modalLogic = createPromptExperimentModalLogic()
        modalLogic.mount()
        modalLogic.actions.submitCreateSuccess(42)

        await expectLogic(logic).toFinishAllListeners()
        expect(mockExperimentsList).toHaveBeenCalledTimes(2)
        modalLogic.unmount()
    })
})
