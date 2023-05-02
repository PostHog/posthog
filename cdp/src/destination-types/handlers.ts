// This file is responsible for handling the destination types API. It's a
// simple API that returns a list of all the available destination types.
//
// The destination types are defined in code for now, but it's possible that we
// will want to move them to the database in the future to allow dynamic
// addition of new destination types.

import Koa from 'koa'

type DestinationType = {
    type: string
    name: string
    description: string
    configSchema: Record<string, unknown> // A JSONSchema describing the configuration
}

const destinationTypes: { [type: string]: DestinationType } = {
    webhook: {
        type: 'webhook',
        name: 'Webhook',
        description: 'Send events to a webhook',
        configSchema: {
            type: 'object',
            properties: {
                url: {
                    type: 'string',
                    description: 'The URL to send the webhook to',
                },
            },
            required: ['url'],
        },
    },
}

export const listDestinationTypes = async (): Promise<DestinationType[]> => {
    return Object.values(destinationTypes)
}

export const listDestinationTypesHandler = async (ctx: Koa.Context): Promise<void> => {
    ctx.status = 200
    ctx.body = await listDestinationTypes()
}
