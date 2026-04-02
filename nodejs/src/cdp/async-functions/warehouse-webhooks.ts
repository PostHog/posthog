import { DateTime } from 'luxon'

import { registerAsyncFunction } from '../async-function-registry'

registerAsyncFunction('produceToWarehouseWebhooks', {
    execute: (args, context, result) => {
        const [payload, explicitSchemaId] = args

        if (!payload || typeof payload !== 'object') {
            throw new Error('[HogFunction] - produceToWarehouseWebhooks requires an object payload')
        }

        if (result.warehouseWebhookPayloads.length > 0) {
            throw new Error(
                'produceToWarehouseWebhooks was called more than once. Only one call is allowed per function'
            )
        }

        // Use explicit schema_id from Hog code args, or fall back to inputs for backward compat
        const schemaId = explicitSchemaId ?? context.invocation.hogFunction.inputs?.schema_id?.value
        if (!schemaId || typeof schemaId !== 'string') {
            throw new Error(
                '[HogFunction] - produceToWarehouseWebhooks requires a schema_id (either as second argument or in hog function inputs)'
            )
        }

        result.warehouseWebhookPayloads.push({
            team_id: context.invocation.teamId,
            schema_id: schemaId,
            payload,
        })
    },

    mock: (args, logs) => {
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `Async function 'produceToWarehouseWebhooks' was mocked with arguments:`,
        })
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `produceToWarehouseWebhooks(${JSON.stringify(args[0], null, 2)})`,
        })

        return { success: true }
    },
})
