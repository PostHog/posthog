import { DateTime } from 'luxon'

import { CyclotronInvocationQueueParametersSendPushNotificationSchema } from '~/cdp/schema/cyclotron'

import { registerAsyncFunction } from '../async-function-registry'

registerAsyncFunction('sendPushNotification', {
    execute: (args, _context, result) => {
        result.invocation.queueParameters = CyclotronInvocationQueueParametersSendPushNotificationSchema.parse({
            ...args[0],
            type: 'sendPushNotification',
        })
    },

    mock: (args, logs) => {
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `Async function 'sendPushNotification' was mocked with arguments:`,
        })
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `sendPushNotification(${JSON.stringify(args[0], null, 2)})`,
        })

        return {
            success: true,
        }
    },
})
