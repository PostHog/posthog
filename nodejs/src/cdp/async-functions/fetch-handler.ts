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

        const fetchQueueParameters = CyclotronInvocationQueueParametersFetchSchema.parse({
            type: 'fetch',
            url,
            method,
            body,
            headers: pickBy(headers, (v) => typeof v == 'string'),
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
