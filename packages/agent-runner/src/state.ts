import { z } from 'zod'

/**
 * Conversation state serialized between turns. Stored as JSON in the queue's BYTEA column.
 *
 * Kept deliberately minimal — the Claude Agent SDK owns the actual conversation log; this
 * envelope just shuttles the SDK state plus runner-level bookkeeping (input messages
 * captured between turns, pending tool calls awaiting a yield).
 */
export const SessionMessageSchema = z.object({
    role: z.enum(['user', 'assistant', 'system']),
    content: z.string(),
    at: z.string().datetime().optional(),
})

export const PendingInputSchema = z.object({
    at: z.string().datetime(),
    content: z.string(),
})

export const SessionStateSchema = z.object({
    /** Conversation history fed back into the SDK on the next turn. */
    messages: z.array(SessionMessageSchema).default([]),
    /** Messages that arrived via /send/:id between turns. */
    pendingInputs: z.array(PendingInputSchema).default([]),
    /** Bundled with the initial input payload when /run created the session. */
    initialInput: z.record(z.string(), z.unknown()).nullable().default(null),
    /** Number of turns the runner has already executed. */
    turnCount: z.number().int().min(0).default(0),
})

export type SessionMessage = z.infer<typeof SessionMessageSchema>
export type PendingInput = z.infer<typeof PendingInputSchema>
export type SessionState = z.infer<typeof SessionStateSchema>

export function emptySessionState(initialInput: Record<string, unknown> | null = null): SessionState {
    return SessionStateSchema.parse({ initialInput })
}

export function serializeState(state: SessionState): Buffer {
    return Buffer.from(JSON.stringify(state), 'utf8')
}

export function deserializeState(buffer: Buffer | null): SessionState {
    if (!buffer || buffer.byteLength === 0) {
        return emptySessionState()
    }
    const raw = JSON.parse(buffer.toString('utf8')) as unknown
    return SessionStateSchema.parse(raw)
}
