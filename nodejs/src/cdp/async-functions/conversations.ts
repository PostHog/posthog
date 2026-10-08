import { DateTime } from 'luxon'

import { HogFlow } from '~/cdp/schema/hogflow'

import { AsyncFunctionContext } from '../async-function-registry'
import { registerAsyncFunction } from '../async-function-registry'
import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult } from '../types'
import { workflowStepDispatchKeyFromInvocation } from '../utils/workflow-step-dispatch-key'
import { UUID_RE, callInternalApi } from './internal-api-call'

const TICKET_ACTIONS = 'ticket workflow actions'

/**
 * Calls the JWT-only internal ticket route (products/conversations/backend/api/internal.py).
 * The token pins the invocation's own team plus this one ticket; Django refuses it anywhere
 * else (#82564).
 */
async function callInternalTicketApi(
    context: AsyncFunctionContext,
    result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>,
    ticketId: string,
    options: {
        method: 'GET' | 'PATCH' | 'POST'
        query?: string
        body?: string
        extraHeaders?: Record<string, string>
        retriableStatuses?: number[]
    }
): Promise<void> {
    // Reaches the operator verbatim in the workflow logs. Keep it free of square brackets,
    // which the log viewer parses as entity chips and would swallow.
    if (!context.conversationsTicketsJwt.enabled) {
        throw new Error(
            `This PostHog deployment has no CONVERSATIONS_TICKETS_JWT_SECRET configured, so ${TICKET_ACTIONS} ` +
                `can't authenticate. Set the same value for the web service and the CDP worker.`
        )
    }
    // The ticket id becomes a URL segment and a token claim, so only a UUID may pass — Hog
    // code controls this value. Lowercased because Django's <uuid:> converter and the claim
    // comparison only accept the canonical form.
    if (!UUID_RE.test(ticketId)) {
        throw new Error(`[HogFunction] - ticket_id must be a UUID, got '${ticketId}'`)
    }
    const canonicalTicketId = ticketId.toLowerCase()
    const { query, ...rest } = options
    await callInternalApi(context, result, {
        jwt: context.conversationsTicketsJwt,
        path: `/api/projects/${context.invocation.teamId}/internal/conversations/tickets/${canonicalTicketId}${query ?? ''}`,
        entityClaims: { ticket_id: canonicalTicketId },
        ...rest,
    })
}

registerAsyncFunction('postHogGetTicket', {
    execute: async (args, context, result) => {
        const [opts] = args as [Record<string, any> | undefined]
        const ticketId = opts?.ticket_id

        if (!ticketId || typeof ticketId !== 'string') {
            throw new Error("[HogFunction] - postHogGetTicket call missing 'ticket_id' property")
        }

        // Opt-in preview of the customer's first message. Only appended when the workflow enabled
        // it, so the default fetch keeps the same URL, response size, and query cost it had.
        const query =
            opts?.include_first_customer_message_text === true ? '?include_first_customer_message_text=true' : ''

        await callInternalTicketApi(context, result, ticketId, { method: 'GET', query })
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
                channel_detail: null,
                distinct_id: 'mock-distinct-id',
                created_at: DateTime.now().toISO(),
                updated_at: DateTime.now().toISO(),
                message_count: 0,
                last_message_at: null,
                last_message_text: null,
                // The real ticket API omits this field unless the caller opts in, so only include
                // it here when the workflow asked for it, keeping a mocked preview true to runtime.
                ...(args[0]?.include_first_customer_message_text === true ? { first_customer_message_text: null } : {}),
                unread_team_count: 0,
                unread_customer_count: 0,
                sla: null,
                snoozed_until: null,
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

        await callInternalTicketApi(context, result, ticketId, {
            method: 'PATCH',
            body: JSON.stringify(updates),
            extraHeaders: hogFlowHeaders,
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

registerAsyncFunction('postHogSendTicketMessage', {
    execute: async (args, context, result) => {
        const [opts] = args as [Record<string, any> | undefined]
        const ticketId = opts?.ticket_id
        const message = typeof opts?.message === 'string' ? opts.message.trim() : ''

        if (!ticketId || typeof ticketId !== 'string') {
            throw new Error("[HogFunction] - postHogSendTicketMessage call missing 'ticket_id' property")
        }
        if (!message) {
            throw new Error("[HogFunction] - postHogSendTicketMessage call missing 'message' property")
        }

        const idempotencyKey = workflowStepDispatchKeyFromInvocation(context.invocation)
        if (!idempotencyKey) {
            throw new Error('[HogFunction] - postHogSendTicketMessage only runs inside a workflow')
        }

        await callInternalTicketApi(context, result, ticketId, {
            method: 'POST',
            body: JSON.stringify({
                message,
                is_private: opts?.is_private === true,
                idempotency_key: idempotencyKey,
            }),
            retriableStatuses: [409],
        })
    },

    mock: (args, logs) => {
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `Async function 'postHogSendTicketMessage' was mocked with arguments:`,
        })
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `postHogSendTicketMessage(${JSON.stringify(args[0], null, 2)})`,
        })

        return {
            status: 201,
            body: {
                id: 'mock-message-id',
                is_private: args[0]?.is_private === true,
            },
        }
    },
})
