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

    it('resumes the same session after the team opts in again', async () => {
        const input = { team: team(true), sessionId: '01a0a4f0-3200-7000-8000-000000000001' }
        expect((await step(input)).type).toBe(PipelineResultType.OK)
        input.team.aiTrainingOptedIn = false
        expect((await step(input)).type).toBe(PipelineResultType.DROP)
        input.team.aiTrainingOptedIn = true
        expect((await step(input)).type).toBe(PipelineResultType.OK)
    })

    it('drops a team that did not opt in', async () => {
        const result = await step({ team: team(false) })
        expect(result.type).toBe(PipelineResultType.DROP)
        expect(result.type === PipelineResultType.DROP && result.reason).toBe('team_not_ai_training_opted_in')
    })
})
