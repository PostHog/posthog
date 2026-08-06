import { DateTime } from 'luxon'

import { CyclotronInvocationQueueParametersFetchSchema } from '~/cdp/schema/cyclotron'
import { HogFlow } from '~/cdp/schema/hogflow'

import { registerAsyncFunction } from '../async-function-registry'

// Ticket steps authenticate to the conversations API with the project's secret API token. That
// setting is nullable with no default, so a project that never minted a key hits this at run time.
// Name the setting and where to fix it rather than surfacing a bare team id.
function missingSecretApiTokenError(siteUrl: string, teamId: number): Error {
    return new Error(
        `This workflow reads or updates a support ticket, but this project has no secret API key configured, ` +
            `so the request can't be authenticated. Generate one under Support settings ` +
            `(${siteUrl}/project/${teamId}/support/settings), then replay this invocation.`
    )
}

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
            throw missingSecretApiTokenError(context.siteUrl, context.invocation.teamId)
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
            throw missingSecretApiTokenError(context.siteUrl, context.invocation.teamId)
        }

        const headers: Record<string, string> = {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${updateTeam.secret_api_token}`,
        }

        // Present only when running inside a HogFlow (spread onto the synthesized invocation);
        // forward the workflow id so the ticket activity log can attribute and link to it. Only
        // the id is sent — the display name is resolved from the workflow on the frontend so it
        // can't be spoofed through this header. Typed as an optional HogFlow so a rename of its
        // id shape breaks compilation here.
        const hogFlow = (context.invocation as { hogFlow?: HogFlow }).hogFlow
        if (hogFlow?.id) {
            headers['X-PostHog-Hog-Flow-Id'] = hogFlow.id
        }

        result.invocation.queueParameters = CyclotronInvocationQueueParametersFetchSchema.parse({
            type: 'fetch',
            url: `${context.siteUrl}/api/conversations/external/ticket/${ticketId}`,
            method: 'PATCH',
            body: JSON.stringify(updates),
            headers,
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
