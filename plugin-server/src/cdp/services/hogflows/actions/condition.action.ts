import { DateTime } from 'luxon'

import { CyclotronJobInvocationHogFlow, HogFunctionFilterGlobals } from '~/src/cdp/types'
import { convertToHogFunctionFilterGlobal } from '~/src/cdp/utils'
import { filterFunctionInstrumented } from '~/src/cdp/utils/hog-function-filtering'
import { HogFlowAction } from '~/src/schema/hogflow'
import { logger } from '~/src/utils/logger'

import { HogFlowActionRunnerResult } from './types'

const DEFAULT_WAIT_DURATION_MINUTES = 10

export class HogFlowActionRunnerCondition {
    run(
        invocation: CyclotronJobInvocationHogFlow,
        action: Extract<HogFlowAction, { type: 'conditional_branch' }>
    ): Promise<HogFlowActionRunnerResult> {
        logger.debug('🦔', `[HogFlowActionRunnerCondition] Running condition action`, {
            action,
            invocation,
        })

        const filterGlobals: HogFunctionFilterGlobals = convertToHogFunctionFilterGlobal({
            event: invocation.state.event, // TODO: Fix typing
            groups: {},
        })

        for (const condition of action.config.conditions) {
            const filterResults = filterFunctionInstrumented({
                fn: invocation.hogFlow,
                filters: condition.filter,
                filterGlobals,
                eventUuid: invocation.state.event.uuid,
            })

            if (filterResults.match) {
                return Promise.resolve({
                    finished: true,
                    goToActionId: condition.on_match,
                })
            }
        }

        // TODO: Add support for some sort of wait condition? Like if we are waiting for a period of time then we can go async

        if (action.config.wait_duration_seconds) {
            const actionStartedAt = DateTime.fromMillis(invocation.state.currentAction?.startedAtTimestamp ?? 0).toUTC()
            if (!invocation.state.currentAction?.startedAtTimestamp || !actionStartedAt.isValid) {
                throw new Error("'currentAction.startedAtTimestamp' is not set or is invalid")
            }

            const waitUntilTime = actionStartedAt.plus({
                seconds: action.config.wait_duration_seconds,
            })

            if (DateTime.utc().diff(waitUntilTime).as('seconds') > 0) {
                // TODO: Add a log to the return to show in the UI
                return Promise.resolve({
                    finished: true,
                    // TODO: Add go to action id? or is this just an indication that the flow is done?
                })
            }

            // We don't want to check to often - by default we will check every 10 minutes or the wait duration whichever is longer
            let scheduledAt = DateTime.utc().plus({ minutes: DEFAULT_WAIT_DURATION_MINUTES })

            if (waitUntilTime.diff(scheduledAt).as('seconds') < 0) {
                scheduledAt = waitUntilTime
            }

            return Promise.resolve({
                finished: false,
                scheduledAt,
            })
        }

        return Promise.resolve({
            finished: true,
        })
    }
}
