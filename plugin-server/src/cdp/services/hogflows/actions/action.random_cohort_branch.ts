import { CyclotronJobInvocationHogFlow } from '~/cdp/types'
import { HogFlowAction } from '~/schema/hogflow'

import { HogFlowActionResult } from './types'
import { findNextAction } from './utils'

type Action = Extract<HogFlowAction, { type: 'random_cohort_branch' }>

export class HogFlowActionRunnerRandomCohortBranch {
    run(invocation: CyclotronJobInvocationHogFlow, action: Action): HogFlowActionResult {
        const random = Math.random() * 100 // 0-100
        let cumulativePercentage = 0

        for (const [index, cohort] of action.config.cohorts.entries()) {
            cumulativePercentage += cohort.percentage
            if (random <= cumulativePercentage) {
                return {
                    done: true,
                    // TODO: Do we error out here if not found?
                    goToAction: findNextAction(invocation.hogFlow, action.id, index),
                }
            }
        }

        // If we somehow get here (shouldn't happen if percentages add up to 100),
        // go to the last cohort
        return {
            done: true,
            goToAction: findNextAction(invocation.hogFlow, action.id, action.config.cohorts.length - 1),
        }
    }
}
