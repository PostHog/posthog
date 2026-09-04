import { DateTime } from 'luxon'

import { CyclotronInvocationQueueParametersFetchSchema } from '~/cdp/schema/cyclotron'
import { HogFlow } from '~/cdp/schema/hogflow'

import { AsyncFunctionContext } from '../async-function-registry'
import { registerAsyncFunction } from '../async-function-registry'
import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult } from '../types'
import { UUID_RE, callInternalApi } from './internal-api-call'
import { getTeamWithSecretToken } from './secret-api-token'

const TICKET_ACTIONS = 'ticket workflow actions'

/**
 * Calls the JWT-only internal ticket route (products/conversations/backend/api/internal.py).
 * The token pins the invocation's own team plus this one ticket; Django refuses it anywhere
 * else. Used whenever CONVERSATIONS_TICKETS_JWT_SECRET is provisioned — the legacy
 * secret_api_token path below it is the fallback until then (#82564).
 */
async function callInternalTicketApi(
    context: AsyncFunctionContext,
    result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>,
    ticketId: string,
    options: { method: 'GET' | 'PATCH'; body?: string; extraHeaders?: Record<string, string> }
): Promise<void> {
    // The ticket id becomes a URL segment and a token claim, so only a UUID may pass — Hog
    // code controls this value. Lowercased because Django's <uuid:> converter and the claim
    // comparison only accept the canonical form.
    if (!UUID_RE.test(ticketId)) {
        throw new Error(`[HogFunction] - ticket_id must be a UUID, got '${ticketId}'`)
    }
    const canonicalTicketId = ticketId.toLowerCase()
    await callInternalApi(context, result, {
        jwt: context.conversationsTicketsJwt,
        path: `/api/projects/${context.invocation.teamId}/internal/conversations/tickets/${canonicalTicketId}`,
        entityClaims: { ticket_id: canonicalTicketId },
        ...options,
    })
}

registerAsyncFunction('postHogGetTicket', {
    execute: async (args, context, result) => {
        const [opts] = args as [Record<string, any> | undefined]
        const ticketId = opts?.ticket_id

        if (!ticketId || typeof ticketId !== 'string') {
            throw new Error("[HogFunction] - postHogGetTicket call missing 'ticket_id' property")
        }

        if (context.conversationsTicketsJwt.enabled) {
            // No team fetch and no secret_api_token requirement: teams that never minted the
            // legacy key can use ticket actions once the JWT secret is provisioned.
            await callInternalTicketApi(context, result, ticketId, { method: 'GET' })
            return
        }

        const team = await getTeamWithSecretToken(context, 'postHogGetTicket', TICKET_ACTIONS)

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

        // Present only when running inside a HogFlow (spread onto the synthesized invocation);
        // forward the workflow id so the ticket activity log can attribute and link to it. Only
        // the id is sent — the display name is resolved from the workflow on the frontend so it
        // can't be spoofed through this header. Typed as an optional HogFlow so a rename of its
        // id shape breaks compilation here.
        const hogFlow = (context.invocation as { hogFlow?: HogFlow }).hogFlow
        const hogFlowHeaders: Record<string, string> = hogFlow?.id ? { 'X-PostHog-Hog-Flow-Id': hogFlow.id } : {}

        if (context.conversationsTicketsJwt.enabled) {
            await callInternalTicketApi(context, result, ticketId, {
                method: 'PATCH',
                body: JSON.stringify(updates),
                extraHeaders: hogFlowHeaders,
            })
            return
        }

        const updateTeam = await getTeamWithSecretToken(context, 'postHogUpdateTicket', TICKET_ACTIONS)

        result.invocation.queueParameters = CyclotronInvocationQueueParametersFetchSchema.parse({
            type: 'fetch',
            url: `${context.siteUrl}/api/conversations/external/ticket/${ticketId}`,
            method: 'PATCH',
            body: JSON.stringify(updates),
            headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${updateTeam.secret_api_token}`,
                ...hogFlowHeaders,
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
