import { DateTime } from 'luxon'

import { CyclotronInvocationQueueParametersMcpEventSchema } from '~/cdp/schema/cyclotron'

import { registerAsyncFunction } from '../async-function-registry'

registerAsyncFunction('mcpEventFetch', {
    execute: (args, context, result): void => {
        if (!Object.hasOwn(context.invocation.hogFunction.encrypted_inputs ?? {}, 'mcp_credential')) {
            throw new Error('MCP event delivery requires a managed subscription.')
        }
        const [url, body] = args
        result.invocation.queueParameters = CyclotronInvocationQueueParametersMcpEventSchema.parse({
            type: 'mcp_event',
            url,
            body: typeof body === 'string' ? body : JSON.stringify(body),
            mcp_event_subscription: {
                id: context.globals.inputs.mcp_subscription_id,
                generation: context.globals.inputs.mcp_generation,
                filter_bytecode: context.invocation.hogFunction.filters?.bytecode,
            },
        })
    },
    mock: (_args, logs): { status: number; body: Record<string, never> } => {
        logs.push({ level: 'info', timestamp: DateTime.now(), message: 'MCP event delivery was mocked.' })
        return { status: 200, body: {} }
    },
})
