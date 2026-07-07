import { describe, expect, it } from 'vitest'

import {
    parseTriggerMetadata,
    SUPPORTED_CLIENT_TOOL_ID_MAX_LEN,
    SUPPORTED_CLIENT_TOOLS_MAX_LEN,
} from './trigger-metadata'

describe('parseTriggerMetadata', () => {
    it.each([
        { kind: 'chat' },
        { kind: 'chat', supported_client_tools: ['connect_mcp', 'set_secret'] },
        { kind: 'slack', workspace_id: 'W', channel: 'C', ts: 't', thread_ts: 't' },
        { kind: 'cron', cron_name: 'daily', schedule: '0 9 * * *', fired_at: '2026-06-25T09:00:00Z' },
        { kind: 'webhook' },
        { kind: 'mcp' },
    ])('accepts %j', (meta) => {
        expect(parseTriggerMetadata(meta)).toEqual(meta)
    })

    it('strips extra keys (e.g. a stale `type` or `client_kind`)', () => {
        expect(
            parseTriggerMetadata({
                kind: 'slack',
                type: 'slack',
                workspace_id: 'W',
                channel: 'C',
                ts: 't',
                thread_ts: 't',
            })
        ).toEqual({
            kind: 'slack',
            workspace_id: 'W',
            channel: 'C',
            ts: 't',
            thread_ts: 't',
        })
        expect(parseTriggerMetadata({ kind: 'chat', client_kind: 'posthog-code' })).toEqual({ kind: 'chat' })
    })

    it.each([null, undefined, {}, 'x', { kind: 'discord' }, { kind: 'slack', channel: 'C' }])(
        'returns null for missing/unknown/incomplete: %j',
        (meta) => {
            expect(parseTriggerMetadata(meta)).toBeNull()
        }
    )

    describe('supported_client_tools bounds', () => {
        it('rejects an array longer than the cap', () => {
            const tools = Array.from({ length: SUPPORTED_CLIENT_TOOLS_MAX_LEN + 1 }, (_, i) => `t${i}`)
            expect(parseTriggerMetadata({ kind: 'chat', supported_client_tools: tools })).toBeNull()
        })

        it('rejects an id longer than the per-element cap', () => {
            const tooLong = 'a'.repeat(SUPPORTED_CLIENT_TOOL_ID_MAX_LEN + 1)
            expect(parseTriggerMetadata({ kind: 'chat', supported_client_tools: [tooLong] })).toBeNull()
        })

        it('rejects an empty-string id', () => {
            expect(parseTriggerMetadata({ kind: 'chat', supported_client_tools: [''] })).toBeNull()
        })

        it('accepts an array at exactly the cap', () => {
            const tools = Array.from({ length: SUPPORTED_CLIENT_TOOLS_MAX_LEN }, (_, i) => `t${i}`)
            expect(parseTriggerMetadata({ kind: 'chat', supported_client_tools: tools })).toEqual({
                kind: 'chat',
                supported_client_tools: tools,
            })
        })
    })

    describe('supported_client_tools normalization', () => {
        it('trims whitespace and dedupes', () => {
            expect(
                parseTriggerMetadata({
                    kind: 'chat',
                    supported_client_tools: ['focus', ' focus ', 'focus', 'toast'],
                })
            ).toEqual({ kind: 'chat', supported_client_tools: ['focus', 'toast'] })
        })

        it('rejects a whitespace-only id (fails min(1) post-trim)', () => {
            expect(parseTriggerMetadata({ kind: 'chat', supported_client_tools: ['   '] })).toBeNull()
        })

        it('preserves first-seen order across duplicates', () => {
            expect(
                parseTriggerMetadata({
                    kind: 'chat',
                    supported_client_tools: ['c', 'a', 'b', 'a', 'c'],
                })
            ).toEqual({ kind: 'chat', supported_client_tools: ['c', 'a', 'b'] })
        })
    })
})
