import { describe, expect, it } from 'vitest'

import { parseTriggerMetadata } from './trigger-metadata'

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
})
