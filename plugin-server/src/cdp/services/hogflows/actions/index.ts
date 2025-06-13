import { HogFlowAction } from '~/src/schema/hogflow'

import { HogFlowActionRunnerCondition } from './condition.action'
import { HogFlowActionRunnerType } from './types'

export const HOG_FLOW_ACTION_RUNNERS: Record<
    HogFlowAction['type'],
    HogFlowActionRunnerType<HogFlowAction> | undefined
> = {
    conditional_branch: HogFlowActionRunnerCondition,
}
