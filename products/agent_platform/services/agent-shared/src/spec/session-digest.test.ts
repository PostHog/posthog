/**
 * Direct unit tests for the pure session-digest helpers (session-digest.ts) —
 * the payload-free view behind the `agent-applications-listen` MCP tool. The ingress route
 * test (services/agent-ingress/src/routing/session-digest.test.ts) drives these
 * over HTTP; here we exercise the builders in isolation so the byte-count,
 * error-count, cursor-split and truncation branches each have a focused case.
 * Fixtures mirror that route test's style (spec types + EMPTY_USAGE_TOTAL).
 */

import {
    buildToolActivityLine,
    DIGEST_MAX_CHARS_DEFAULT,
    renderSessionDigest,
    toolResultBytes,
    usageLine,
} from './session-digest'
import {
    type AgentSession,
    type ConversationMessage,
    EMPTY_USAGE_TOTAL,
    type ImageContent,
    type SessionUsageTotal,
    type TextContent,
} from './spec'

const SESSION_ID = 'sess-aaaa-bbbb'
const APP_ID = 'app-1111-2222'

/** Minimal AgentSession fixture — only the fields renderSessionDigest reads
 *  (`state`, `conversation`, `usage_total`) carry meaning; the rest satisfy the
 *  type. */
function makeSession(overrides: Partial<AgentSession> = {}): AgentSession {
    return {
        id: SESSION_ID,
        application_id: APP_ID,
        revision_id: 'rev-1',
        team_id: 1,
        external_key: null,
        idempotency_key: null,
        trigger_metadata: null,
        state: 'running',
        principal: null,
        conversation: [],
        pending_inputs: [],
        retry_count: 0,
        usage_total: { ...EMPTY_USAGE_TOTAL },
        acl: [],
        pending_elevation_requests: [],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        ...overrides,
    } as AgentSession
}

function assistantText(text: string): ConversationMessage {
    return { role: 'assistant', content: [{ type: 'text', text }], timestamp: Date.now() }
}

function assistantToolCall(name: string): ConversationMessage {
    return {
        role: 'assistant',
        content: [{ type: 'toolCall', id: `call-${name}`, name, arguments: {} }],
        timestamp: Date.now(),
    }
}

function toolResult(toolName: string, content: (TextContent | ImageContent)[], isError = false): ConversationMessage {
    return {
        role: 'toolResult',
        toolCallId: `call-${toolName}`,
        toolName,
        content,
        isError,
        timestamp: Date.now(),
    }
}

function text(t: string): TextContent {
    return { type: 'text', text: t }
}

describe('buildToolActivityLine', () => {
    it('summarizes a single tool call + result as `name ×1, <bytes>B`', () => {
        const slice: ConversationMessage[] = [assistantToolCall('bash'), toolResult('bash', [text('hello')])]
        const line = buildToolActivityLine(slice)
        // 'hello' is 5 ASCII bytes.
        expect(line).toBe('bash ×1, 5B')
    })

    it('lists TWO distinct tools, joined by `; `', () => {
        const slice: ConversationMessage[] = [
            assistantToolCall('bash'),
            toolResult('bash', [text('ok')]),
            assistantToolCall('search'),
            toolResult('search', [text('rows')]),
        ]
        const line = buildToolActivityLine(slice)
        expect(line).toContain('bash ×1, 2B')
        expect(line).toContain('search ×1, 4B')
        expect(line).toContain('; ')
        expect(line.split('; ')).toHaveLength(2)
    })

    it('counts an errored tool result with `err×1`', () => {
        const slice: ConversationMessage[] = [assistantToolCall('bash'), toolResult('bash', [text('boom')], true)]
        const line = buildToolActivityLine(slice)
        expect(line).toContain('err×1')
        expect(line).toBe('bash ×1, 4B, err×1')
    })

    it('reports `name ×0` for a result whose matching call fell before the cursor', () => {
        // The slice split the call (before cursor) from its result (after) — the
        // tool still appears, with zero calls counted in this window.
        const slice: ConversationMessage[] = [toolResult('search', [text('late rows')])]
        const line = buildToolActivityLine(slice)
        expect(line).toContain('search ×0')
    })

    it('returns "" for an empty slice / a slice with no tools', () => {
        expect(buildToolActivityLine([])).toBe('')
        expect(buildToolActivityLine([assistantText('just talking')])).toBe('')
    })
})

describe('toolResultBytes', () => {
    it('counts text content as its utf8 byte length', () => {
        // 'héllo' — the é is 2 bytes in utf8, so 6 bytes for 5 code points.
        expect(toolResultBytes([text('héllo')])).toBe(Buffer.byteLength('héllo', 'utf8'))
        expect(toolResultBytes([text('héllo')])).toBe(6)
    })

    it('counts image content as the base64 data length', () => {
        const data = 'aGVsbG8='
        const image: ImageContent = { type: 'image', data, mimeType: 'image/png' }
        expect(toolResultBytes([image])).toBe(data.length)
    })
})

describe('renderSessionDigest', () => {
    it('renders `(no assistant text yet)` + turns=0 + truncated:false for an empty conversation', () => {
        const session = makeSession({ conversation: [] })
        const { digest, truncated } = renderSessionDigest(session, [], 0, DIGEST_MAX_CHARS_DEFAULT)
        expect(digest).toContain('(no assistant text yet)')
        expect(digest).toContain('turns=0')
        expect(truncated).toBe(false)
    })

    it('falls back to the conversation-wide last assistant text when the slice has only tool traffic', () => {
        const conversation: ConversationMessage[] = [
            assistantText('earlier answer'),
            assistantToolCall('bash'),
            toolResult('bash', [text('output')]),
        ]
        const session = makeSession({ conversation })
        // Slice is only the tool traffic (cursor past the assistant text).
        const slice = conversation.slice(1)
        const { digest } = renderSessionDigest(session, slice, conversation.length, DIGEST_MAX_CHARS_DEFAULT)
        expect(digest).toContain('earlier answer')
    })

    it('reports truncated:false for a small digest', () => {
        const conversation: ConversationMessage[] = [assistantText('short reply')]
        const session = makeSession({ conversation })
        const { digest, truncated } = renderSessionDigest(session, conversation, 1, DIGEST_MAX_CHARS_DEFAULT)
        expect(truncated).toBe(false)
        expect(digest).toContain('short reply')
    })

    it('clips a large digest to <= maxChars code points and ends with the re-poll pointer', () => {
        const conversation: ConversationMessage[] = [assistantText('x'.repeat(5_000))]
        const session = makeSession({ conversation })
        const MAX = 200
        const { digest, truncated } = renderSessionDigest(session, conversation, 1, MAX)
        expect(truncated).toBe(true)
        expect(Array.from(digest).length).toBeLessThanOrEqual(MAX)
        expect(digest).toContain('…[digest clipped; re-poll with cursor=1]')
    })

    it('never exceeds maxChars even when maxChars is smaller than the pointer', () => {
        const conversation: ConversationMessage[] = [assistantText('x'.repeat(5_000))]
        const session = makeSession({ conversation })
        const MAX = 10 // smaller than the ~40-char pointer — the hard cap must win
        const { digest, truncated } = renderSessionDigest(session, conversation, 1, MAX)
        expect(truncated).toBe(true)
        expect(Array.from(digest).length).toBeLessThanOrEqual(MAX)
    })
})

describe('usageLine', () => {
    it('formats tokens_in / tokens_out / cost_total', () => {
        const usage: SessionUsageTotal = {
            ...EMPTY_USAGE_TOTAL,
            tokens_in: 120,
            tokens_out: 34,
            cost_total: 0.5,
        }
        expect(usageLine(usage)).toBe('tokens_in=120 tokens_out=34 cost_total=0.5')
    })
})
