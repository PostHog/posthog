import { pickBy } from 'lodash'
import { DateTime } from 'luxon'
import { randomUUID } from 'node:crypto'

import { CyclotronInvocationQueueParametersFetchSchema } from '~/cdp/schema/cyclotron'
import { parseJSON } from '~/common/utils/json-parse'

import { type AsyncFunctionHandler, registerAsyncFunction } from '../async-function-registry'

const fetchHandler: AsyncFunctionHandler = {
    execute: (args, context, result) => {
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
        // signature past AWS's 5-minute expiry window. Only include the key when
        // it's actually set — Zod preserves an `aws_sigv4: undefined` own property
        // on the parsed object, which would otherwise leak into every non-AWS
        // template's queueParameters snapshot.
        // The reserved input marks managed destinations without changing ordinary custom headers.
        const managedMcp = Object.hasOwn(context.invocation?.hogFunction?.encrypted_inputs ?? {}, 'mcp_credential')
        const mcpSubscription = managedMcp
            ? {
                  id: headers['X-MCP-Subscription-Id'],
                  generation: context.globals?.inputs?.mcp_generation,
                  filter_bytecode: context.invocation.hogFunction.filters?.bytecode,
              }
            : undefined
        const eventId = mcpSubscription && body ? parseJSON(body).eventId : undefined

        const fetchQueueParameters = CyclotronInvocationQueueParametersFetchSchema.parse({
            type: managedMcp ? 'mcp_event' : 'fetch',
            url,
            method,
            body,
            headers: pickBy(headers, (v) => typeof v == 'string'),
            ...(mcpSubscription ? { mcp_event_subscription: mcpSubscription } : {}),
            ...(fetchOptions?.aws_sigv4 ? { aws_sigv4: fetchOptions.aws_sigv4 } : {}),
            ...(fetchOptions?.secret_headers_input ? { secret_headers_input: fetchOptions.secret_headers_input } : {}),
            // Receivers deduplicate retries by this id. Producers with a stable
            // event id can also deduplicate repeated processing of the source event.
            ...(fetchOptions?.standard_webhooks
                ? {
                      standard_webhooks: {
                          ...fetchOptions.standard_webhooks,
                          webhook_id: eventId ?? fetchOptions.standard_webhooks.webhook_id ?? randomUUID(),
                      },
                  }
                : {}),
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
}

registerAsyncFunction('fetch', fetchHandler)
registerAsyncFunction('mcpEventFetch', {
    execute: (args, context, result) => {
        if (!Object.hasOwn(context.invocation?.hogFunction?.encrypted_inputs ?? {}, 'mcp_credential')) {
            throw new Error('MCP event delivery requires a managed subscription.')
        }
        return fetchHandler.execute(args, context, result)
    },
    mock: fetchHandler.mock,
})
