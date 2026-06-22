import { pickBy } from 'lodash'
import { DateTime } from 'luxon'

import { CyclotronInvocationQueueParametersFetchSchema } from '~/schema/cyclotron'

import { registerAsyncFunction } from '../async-function-registry'

registerAsyncFunction('fetch', {
    execute: (args, _context, result) => {
        const [url, fetchOptions] = args as [string | undefined, Record<string, any> | undefined]

        const method = fetchOptions?.method || 'POST'
        const headers = fetchOptions?.headers || {
            'Content-Type': 'application/json',
        }

        const body: string | undefined = fetchOptions?.body
            ? typeof fetchOptions.body === 'string'
                ? fetchOptions.body
                : JSON.stringify(fetchOptions.body)
            : fetchOptions?.body

        // Hog templates targeting AWS services (Kinesis, SQS, …) pass `aws_sigv4`
        // here instead of computing the Authorization header in Hog. The fetch
        // executor re-signs on every attempt so a retry can never carry a stale
        // signature past AWS's 5-minute expiry window.
        const fetchQueueParameters = CyclotronInvocationQueueParametersFetchSchema.parse({
            type: 'fetch',
            url,
            method,
            body,
            headers: pickBy(headers, (v) => typeof v == 'string'),
            aws_sigv4: fetchOptions?.aws_sigv4,
        })

        result.invocation.queueParameters = fetchQueueParameters
    },

    mock: (args, logs) => {
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `Async function 'fetch' was mocked with arguments:`,
        })
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `fetch('${args[0]}', ${JSON.stringify(args[1], null, 2)})`,
        })

        return {
            status: 200,
            body: {},
        }
    },
})
