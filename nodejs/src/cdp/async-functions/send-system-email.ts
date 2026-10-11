import { DateTime } from 'luxon'

import { logger } from '~/common/utils/logger'

import { registerAsyncFunction } from '../async-function-registry'
import { SystemEmailResult } from '../services/messaging/system-email.service'

registerAsyncFunction('sendSystemEmail', {
    // Sends inline and never stages queueParameters. Only the messaging workers serve the 'email'
    // queue, and the hog worker that runs internal destinations cannot produce to it.
    execute: async (args, context, result) => {
        let response: SystemEmailResult
        // A test run takes its event, and so its recipients, from the caller. Live mail would let a
        // function editor send text from the PostHog address to any member of the organization.
        if (context.isTest) {
            result.invocation.state.vmState?.stack.push({
                success: false,
                error: "Test runs can't send alert email.",
            })
            return
        }
        try {
            context.consumeInlineAsyncBudget()
            response = await context.systemEmailService.sendFromInvocation(args[0], result)
        } catch (error) {
            logger.error('[SystemEmail] sendSystemEmail failed', {
                teamId: result.invocation.teamId,
                functionId: result.invocation.functionId,
                errorName: error instanceof Error ? error.name : 'unknown',
            })
            response = { success: false, error: "Couldn't send the email. Try again later." }
        }
        result.invocation.state.vmState?.stack.push(response)
    },

    mock: (args, logs) => {
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `Async function 'sendSystemEmail' was mocked with arguments:`,
        })
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `sendSystemEmail(${JSON.stringify(args[0], null, 2)})`,
        })

        return {
            success: true,
        }
    },
})
