import { HogFlowAction } from '~/schema/hogflow'

import { HogFlowActionRunnerResult } from './types'

type Action = Extract<HogFlowAction, { type: 'random_cohort_branch' }>

export class HogFlowActionRunnerRandomCohortBranch {
    run(action: Action): Omit<HogFlowActionRunnerResult, 'action'> {
        const random = Math.random() * 100 // 0-100
        let cumulativePercentage = 0

        for (const cohort of action.config.cohorts) {
            cumulativePercentage += cohort.percentage
            if (random <= cumulativePercentage) {
                return {
                    finished: true,
                    goToActionId: cohort.on_match,
                }
            }
        }

        // If we somehow get here (shouldn't happen if percentages add up to 100),
        // go to the last cohort
        const lastCohort = action.config.cohorts[action.config.cohorts.length - 1]
        return {
            finished: true,
            goToActionId: lastCohort.on_match,
        }
    }
}
