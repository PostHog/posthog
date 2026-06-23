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

// Anthropic vision accepts these MIME types; svg+xml is explicitly rejected.
// Match the set in `UserMessage.content` (see agent-shared spec.ts).
const IMAGE_MIME_TYPES = ['image/png', 'image/jpeg', 'image/gif', 'image/webp'] as const

// Per-block size guards. Base64 inflates binary by ~33%, so a 5 MiB raw image
// arrives as ~6.7 MiB on the wire — match against the encoded length here.
// Anthropic's documented per-image ceiling is 5 MiB decoded.
const MAX_IMAGE_BASE64_BYTES = 7 * 1024 * 1024
const MAX_TEXT_BLOCK_BYTES = 1 * 1024 * 1024

const TextContentSchema = z.object({
    type: z.literal('text'),
    text: z
        .string()
        .min(1, 'text must be a non-empty string')
        .max(MAX_TEXT_BLOCK_BYTES, `text block exceeds ${MAX_TEXT_BLOCK_BYTES} bytes`),
})

const ImageContentSchema = z.object({
    type: z.literal('image'),
    data: z
        .string()
        .min(1, 'data must be a non-empty base64 string')
        .max(MAX_IMAGE_BASE64_BYTES, `image data exceeds ${MAX_IMAGE_BASE64_BYTES} bytes (base64)`),
    mimeType: z.enum(IMAGE_MIME_TYPES),
})

// The shape mirrors `UserMessage.content` in agent-shared/spec.ts — string for
// plain-text legacy callers, or an array of content blocks for multimodal.
const MessageContentSchema = z.union([
    z.string().min(1, 'message must be a non-empty string'),
    z.array(z.union([TextContentSchema, ImageContentSchema])).min(1, 'message must contain at least one block'),
])

export const ChatRunBodySchema = z.object({
    message: MessageContentSchema,
    external_key: z.string().optional(),
})

/**
 * Body for `POST /agents/<slug>/send`. Either a chat `message`, or a
 * `client_tool_result` for interactive (parked) client tools.
 */
export const ChatSendBodySchema = z
    .object({
        session_id: z.string().uuid('session_id must be a UUID'),
        message: MessageContentSchema.optional(),
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
