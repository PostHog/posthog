import { DateTime } from 'luxon'

import { CyclotronInvocationQueueParametersEmailSchema } from '~/cdp/schema/cyclotron'
import { acceptedSendEmailFields } from '~/cdp/services/hogflows/transactional-email'
import { emailTemplate } from '~/cdp/services/messaging/helpers/transactional-email-identity'

import { registerAsyncFunction } from '../async-function-registry'

registerAsyncFunction('sendEmail', {
    execute: (args, context, result) => {
        const { attachments: _onlyAnAcceptedSendHasFiles, ...stepEmail } = args[0] ?? {}
        result.invocation.queueParameters = CyclotronInvocationQueueParametersEmailSchema.parse({
            ...stepEmail,
            ...acceptedSendEmailFields(context.invocation.state.send),
            template: emailTemplate(context.invocation.hogFunction?.metadata),
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
