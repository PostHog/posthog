import { DateTime } from 'luxon'

import { CyclotronJobInvocationHogFlow } from '~/cdp/types'
import { HogFlowAction } from '~/schema/hogflow'
import { logger } from '~/utils/logger'

import { HogFlowActionRunnerResult } from './types'

const DEFAULT_WAIT_DURATION_MINUTES = 10

export class HogFlowActionRunnerDelay {
    run(
        invocation: CyclotronJobInvocationHogFlow,
        action: Extract<HogFlowAction, { type: 'delay' }>
    ): Promise<HogFlowActionRunnerResult> {
        logger.debug('🦔', `[HogFlowActionRunnerDelay] Running delay action`, {
            action,
            invocation,
        })

        if (!action.config.delay_seconds) {
            throw new Error('delay_seconds is required')
        }

        const actionStartedAt = DateTime.fromMillis(invocation.state.currentAction?.startedAtTimestamp ?? 0).toUTC()
        if (!invocation.state.currentAction?.startedAtTimestamp || !actionStartedAt.isValid) {
            throw new Error("'currentAction.startedAtTimestamp' is not set or is invalid")
        }

        const waitUntilTime = actionStartedAt.plus({
            seconds: action.config.delay_seconds,
        })

        if (DateTime.utc().diff(waitUntilTime).as('seconds') > 0) {
            return Promise.resolve({
                finished: true,
                goToActionId: invocation.hogFlow.edges.find((edge) => edge.from === action.id)?.to,
            })
        }

        let scheduledAt = DateTime.utc().plus({ minutes: DEFAULT_WAIT_DURATION_MINUTES })

        if (waitUntilTime.diff(scheduledAt).as('seconds') < 0) {
            scheduledAt = waitUntilTime
        }

        return Promise.resolve({
            finished: false,
            scheduledAt,
        })
    }
}
