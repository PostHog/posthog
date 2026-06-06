import { DateTime } from 'luxon'

import { CyclotronInvocationQueueParametersEmailSchema } from '~/schema/cyclotron'

import { registerAsyncFunction } from '../async-function-registry'

registerAsyncFunction('sendEmail', {
    execute: (args, _context, result) => {
        result.invocation.queueParameters = CyclotronInvocationQueueParametersEmailSchema.parse({
            ...args[0],
            type: 'email',
        })
    },

    mock: (args, logs) => {
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `Async function 'sendEmail' was mocked with arguments:`,
        })
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `sendEmail(${JSON.stringify(args[0], null, 2)})`,
        })

        return {
            success: true,
        }
    },
})
