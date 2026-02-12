import { DateTime } from 'luxon'

import { CyclotronInvocationQueueParametersFetchSchema } from '~/schema/cyclotron'

import { registerAsyncFunction } from '../async-function-registry'

registerAsyncFunction('postHogGetTicket', {
    execute: async (args, context, result) => {
        const [opts] = args as [Record<string, any> | undefined]
        const ticketId = opts?.ticket_id

        if (!ticketId || typeof ticketId !== 'string') {
            throw new Error("[HogFunction] - postHogGetTicket call missing 'ticket_id' property")
        }

        const team = await context.hub.teamManager.getTeam(context.invocation.teamId)
        if (!team) {
            throw new Error(`Team ${context.invocation.teamId} not found`)
        }

        result.invocation.queueParameters = CyclotronInvocationQueueParametersFetchSchema.parse({
            type: 'fetch',
            url: `${context.hub.SITE_URL}/api/conversations/external/ticket/${ticketId}`,
            method: 'GET',
            headers: { Authorization: `Bearer ${team.api_token}` },
        })
    },

    mock: (args, logs) => {
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `Async function 'postHogGetTicket' was mocked with arguments:`,
        })
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `postHogGetTicket(${JSON.stringify(args[0], null, 2)})`,
        })

        return {
            status: 200,
            body: {
                id: args[0]?.ticket_id ?? 'mock-ticket-id',
                status: 'new',
                priority: null,
                ticket_number: 1,
                channel_source: 'widget',
                message_count: 0,
                last_message_at: null,
                last_message_text: null,
                unread_team_count: 0,
                unread_customer_count: 0,
            },
        }
    },
})

registerAsyncFunction('postHogUpdateTicket', {
    execute: async (args, context, result) => {
        const [opts] = args as [Record<string, any> | undefined]
        const ticketId = opts?.ticket_id
        const updates = opts?.updates || {}

        if (!ticketId || typeof ticketId !== 'string') {
            throw new Error("[HogFunction] - postHogUpdateTicket call missing 'ticket_id' property")
        }

        const updateTeam = await context.hub.teamManager.getTeam(context.invocation.teamId)
        if (!updateTeam) {
            throw new Error(`Team ${context.invocation.teamId} not found`)
        }

        result.invocation.queueParameters = CyclotronInvocationQueueParametersFetchSchema.parse({
            type: 'fetch',
            url: `${context.hub.SITE_URL}/api/conversations/external/ticket/${ticketId}`,
            method: 'PATCH',
            body: JSON.stringify(updates),
            headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${updateTeam.api_token}`,
            },
        })
    },

    mock: (args, logs) => {
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `Async function 'postHogUpdateTicket' was mocked with arguments:`,
        })
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `postHogUpdateTicket(${JSON.stringify(args[0], null, 2)})`,
        })

        return {
            status: 200,
            body: { ok: true },
        }
    },
})
