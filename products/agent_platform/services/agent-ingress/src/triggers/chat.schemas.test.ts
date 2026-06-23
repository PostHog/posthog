import { describe, expect, it } from 'vitest'

import { ChatRunBodySchema, ChatSendBodySchema } from './chat.schemas'

const VALID_SESSION_ID = '00000000-0000-4000-8000-000000000000'

describe('ChatRunBodySchema', () => {
    it('accepts a bare string message (legacy single-string callers)', () => {
        const result = ChatRunBodySchema.safeParse({ message: 'tell me a joke' })
        expect(result.success).toBe(true)
    })

    it('accepts a text content block (markdown / plain text upload path)', () => {
        const result = ChatRunBodySchema.safeParse({
            message: [{ type: 'text', text: '# heading\n\nsome markdown' }],
        })
        expect(result.success).toBe(true)
    })

    it('accepts an image content block with an allowlisted mime type', () => {
        const result = ChatRunBodySchema.safeParse({
            message: [{ type: 'image', data: 'aGVsbG8=', mimeType: 'image/png' }],
        })
        expect(result.success).toBe(true)
    })

    it('accepts a mixed text + image block', () => {
        const result = ChatRunBodySchema.safeParse({
            message: [
                { type: 'text', text: 'look at this:' },
                { type: 'image', data: 'aGVsbG8=', mimeType: 'image/jpeg' },
            ],
        })
        expect(result.success).toBe(true)
    })

    it('rejects an empty content block array', () => {
        const result = ChatRunBodySchema.safeParse({ message: [] })
        expect(result.success).toBe(false)
    })

    it('rejects an empty string', () => {
        const result = ChatRunBodySchema.safeParse({ message: '' })
        expect(result.success).toBe(false)
    })

    it('rejects image/svg+xml (anthropic vision allowlist + xss risk)', () => {
        const result = ChatRunBodySchema.safeParse({
            message: [{ type: 'image', data: 'PHN2Zy8+', mimeType: 'image/svg+xml' }],
        })
        expect(result.success).toBe(false)
    })

    it('rejects image data above the per-block size guard', () => {
        // 8 MiB of base64 exceeds the 7 MiB ceiling — picks up an over-budget
        // image without the express body limit having to bounce it.
        const oversized = 'A'.repeat(8 * 1024 * 1024)
        const result = ChatRunBodySchema.safeParse({
            message: [{ type: 'image', data: oversized, mimeType: 'image/png' }],
        })
        expect(result.success).toBe(false)
    })

    it('rejects an unknown content block type', () => {
        const result = ChatRunBodySchema.safeParse({
            message: [{ type: 'audio', data: 'aGVsbG8=' }],
        })
        expect(result.success).toBe(false)
    })
})

describe('ChatSendBodySchema', () => {
    it('accepts a content-block message when session_id is present', () => {
        const result = ChatSendBodySchema.safeParse({
            session_id: VALID_SESSION_ID,
            message: [{ type: 'text', text: 'follow-up' }],
        })
        expect(result.success).toBe(true)
    })

    it('still enforces message XOR client_tool_result with the wider message shape', () => {
        const both = ChatSendBodySchema.safeParse({
            session_id: VALID_SESSION_ID,
            message: [{ type: 'text', text: 'hi' }],
            client_tool_result: { call_id: 'c1', result: {} },
        })
        expect(both.success).toBe(false)

        const neither = ChatSendBodySchema.safeParse({ session_id: VALID_SESSION_ID })
        expect(neither.success).toBe(false)
    })
})
