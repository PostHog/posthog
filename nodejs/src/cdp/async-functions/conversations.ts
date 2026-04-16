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

        const team = await context.teamManager.getTeam(context.invocation.teamId)
        if (!team) {
            throw new Error(`Team ${context.invocation.teamId} not found`)
        }
        if (!team.secret_api_token) {
            throw new Error(`Team ${context.invocation.teamId} has no secret API token configured`)
        }

        result.invocation.queueParameters = CyclotronInvocationQueueParametersFetchSchema.parse({
            type: 'fetch',
            url: `${context.siteUrl}/api/conversations/external/ticket/${ticketId}`,
            method: 'GET',
            headers: { Authorization: `Bearer ${team.secret_api_token}` },
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
                number: 1,
                status: 'new',
                priority: null,
                channel_source: 'widget',
                distinct_id: 'mock-distinct-id',
                created_at: DateTime.now().toISO(),
                updated_at: DateTime.now().toISO(),
                message_count: 0,
                last_message_at: null,
                last_message_text: null,
                unread_team_count: 0,
                unread_customer_count: 0,
                sla: null,
                assignee: null,
                url: null,
                slack_channel_id: null,
                slack_thread_ts: null,
                slack_team_id: null,
                email_subject: null,
                email_from: null,
                email_to: null,
                cc_participants: [],
                tags: [],
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

        const updateTeam = await context.teamManager.getTeam(context.invocation.teamId)
        if (!updateTeam) {
            throw new Error(`Team ${context.invocation.teamId} not found`)
        }
        if (!updateTeam.secret_api_token) {
            throw new Error(`Team ${context.invocation.teamId} has no secret API token configured`)
        }

        result.invocation.queueParameters = CyclotronInvocationQueueParametersFetchSchema.parse({
            type: 'fetch',
            url: `${context.siteUrl}/api/conversations/external/ticket/${ticketId}`,
            method: 'PATCH',
            body: JSON.stringify(updates),
            headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${updateTeam.secret_api_token}`,
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
