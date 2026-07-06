import { PipelineResultType } from '~/ingestion/framework/results'

import { createAiTrainingOptInFilterStep } from './ai-training-optin-filter-step'
import { TeamForReplay } from './teams/types'

describe('ai-training-optin-filter-step', () => {
    const step = createAiTrainingOptInFilterStep()
    const team = (aiTrainingOptedIn: boolean): TeamForReplay => ({
        teamId: 1,
        consoleLogIngestionEnabled: false,
        aiTrainingOptedIn,
    })

    it('passes through a team that opted into AI training', async () => {
        const input = { team: team(true) }
        const result = await step(input)
        expect(result.type).toBe(PipelineResultType.OK)
    })

    it('drops a team that did not opt in', async () => {
        const result = await step({ team: team(false) })
        expect(result.type).toBe(PipelineResultType.DROP)
        expect(result.type === PipelineResultType.DROP && result.reason).toBe('team_not_ai_training_opted_in')
    })
})
