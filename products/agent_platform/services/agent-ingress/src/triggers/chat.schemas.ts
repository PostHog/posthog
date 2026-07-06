/**
 * Body / query schemas for the chat trigger.
 *
 * Living source of truth: this file. The HTTP handlers `safeParse` against
 * these zod schemas at the trigger edge (so silent coercion of bad payloads
 * to empty strings can't happen), and the `chatTrigger` module in `chat.ts`
 * runs `z.toJSONSchema` over them to populate its `routes` array — which the
 * ingress then publishes via `GET /agents/<slug>/schemas`. One source for the
 * parse and for discovery.
 */

import { z } from 'zod'

import { SUPPORTED_CLIENT_TOOL_ID_MAX_LEN, SUPPORTED_CLIENT_TOOLS_MAX_LEN } from '@posthog/agent-shared'

export const ChatRunBodySchema = z.object({
    message: z.string().min(1, 'message must be a non-empty string'),
    external_key: z.string().optional(),
    // `kind:'client'` tool ids this client can fulfil; the runner exposes the
    // matching spec tools to the model. UX hint, never a security boundary.
    // Capped to stop a misbehaving caller from inflating the session row's
    // `trigger_metadata` JSONB. Bounds mirror trigger-metadata.ts.
    supported_client_tools: z
        .array(z.string().min(1).max(SUPPORTED_CLIENT_TOOL_ID_MAX_LEN))
        .max(SUPPORTED_CLIENT_TOOLS_MAX_LEN)
        .optional(),
})

/**
 * Body for `POST /agents/<slug>/send`. Either a chat `message`, or a
 * `client_tool_result` for interactive (parked) client tools.
 */
export const ChatSendBodySchema = z
    .object({
        session_id: z.string().uuid('session_id must be a UUID'),
        message: z.string().min(1, 'message must be a non-empty string').optional(),
        client_tool_result: z
            .object({
                call_id: z.string().min(1, 'call_id is required'),
                result: z.record(z.string(), z.unknown()).optional(),
                error: z.string().optional(),
            })
            .refine((v) => v.result !== undefined || typeof v.error === 'string', {
                message: 'exactly one of `result` or `error` must be set',
                path: ['result'],
            })
            .optional(),
    })
    .refine(
        (v) =>
            (v.message !== undefined && v.client_tool_result === undefined) ||
            (v.message === undefined && v.client_tool_result !== undefined),
        {
            message: 'exactly one of `message` or `client_tool_result` must be set',
            path: ['message'],
        }
    )

export const ChatCancelBodySchema = z.object({
    session_id: z.string().uuid('session_id must be a UUID'),
})

export const ChatListenQuerySchema = z.object({
    session_id: z.string().uuid('session_id must be a UUID'),
})

/**
 * Body for `POST /agents/<slug>/client_tool_result`. Fired by the
 * connecting client (browser dock, IDE MCP host) to answer a
 * `client_tool_call` event the runner emitted. Exactly one of
 * `result` / `error` must be set. The runner side awaits a matching
 * `client_tool_result` bus event with the same `call_id`.
 */
export const ChatClientToolResultBodySchema = z
    .object({
        session_id: z.string().uuid('session_id must be a UUID'),
        call_id: z.string().min(1, 'call_id is required'),
        result: z.unknown().optional(),
        error: z.string().optional(),
    })
    .refine((v) => v.result !== undefined || typeof v.error === 'string', {
        message: 'exactly one of `result` or `error` must be set',
        path: ['result'],
    })
