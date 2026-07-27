import { describe, expect, it, vi } from 'vitest'

import { AgentApplication, AgentRevision, AgentSession } from '../spec/spec'
import {
    categorize,
    FailureNotifier,
    NoopFailureNotifier,
    TriggerAwareFailureNotifier,
    userFacingMessage,
} from './failure-notifier'
import type { TriggerMetadata } from './trigger-metadata'

const APP: AgentApplication = {
    id: 'app-1',
    team_id: 1,
    slug: 'demo',
    name: 'demo',
    description: '',
    live_revision_id: null,
    archived: false,
}

const REV: AgentRevision = {
    id: 'rev-1',
    application_id: APP.id,
    parent_revision_id: null,
    created_by_id: null,
    created_at: new Date().toISOString(),
    state: 'live',
    bundle_uri: 's3://x/',
    bundle_sha256: null,
    spec: { model: 'anthropic/claude-sonnet-4-6' } as unknown as AgentRevision['spec'],
    encrypted_env: null,
}

function makeSession(triggerMetadata: TriggerMetadata | null): AgentSession {
    return {
        id: 'sess-1',
        application_id: APP.id,
        revision_id: 'rev-1',
        team_id: 1,
        external_key: null,
        idempotency_key: null,
        trigger_metadata: triggerMetadata,
        state: 'failed',
        conversation: [],
        pending_inputs: [],
        principal: null,
        retry_count: 0,
        usage_total: { input_tokens: 0, output_tokens: 0, cost_total: 0 },
        acl: [],
        pending_elevation_requests: [],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
    } as unknown as AgentSession
}

describe('categorize', () => {
    it.each([
        ["docker run failed: Unable to find image 'posthog/agent-sandbox-host:v1'", 'transient_infra'],
        ['pull access denied for posthog/agent-sandbox-host', 'transient_infra'],
        ['Modal sandbox cold-start timed out', 'transient_infra'],
        ['kafka producer error: ECONNREFUSED', 'transient_infra'],
        ['redis connection lost', 'transient_infra'],
        ['ETIMEDOUT', 'transient_infra'],

        ['missing required secret SLACK_BOT_TOKEN', 'configuration'],
        ['signing_secret_resolver returned null', 'configuration'],
        ['MCP open failed: bad_url', 'configuration'],
        ['invalid spec at triggers[0].config', 'configuration'],
        ['no_bot_token', 'configuration'],
        ['bundle_missing for revision rev-xyz', 'configuration'],
        ['revision_missing', 'configuration'],

        ['429 Too Many Requests', 'quota_exhausted'],
        ['model returned rate_limit', 'quota_exhausted'],
        ['max_turns_exceeded', 'quota_exhausted'],
        ['output_truncated', 'quota_exhausted'],
        ['quota exceeded', 'quota_exhausted'],

        ['tool threw at dispatcher', 'tool_error'],
        ['tool_call_failed: timeout', 'tool_error'],
        ['sandbox timeout after 30s', 'transient_infra'], // sandbox keyword wins → infra

        ['client_tool_unsupported:connect_mcp', 'capability_mismatch'],
        ['Error: client_tool_unsupported:set_secret', 'capability_mismatch'],

        ['client_tool_dispatcher_unavailable:focus', 'configuration'],
    ])('"%s" → %s', (reason, expected) => {
        expect(categorize(reason)).toBe(expected)
    })

    it('returns `unknown` on no match — never falls through to raw', () => {
        expect(categorize('arglebargle')).toBe('unknown')
        expect(categorize('')).toBe('unknown')
    })
})

describe('userFacingMessage', () => {
    it('returns a stable string per category', () => {
        expect(userFacingMessage('transient_infra')).toMatch(/try again/i)
        expect(userFacingMessage('configuration')).toMatch(/owner/i)
        expect(userFacingMessage('quota_exhausted')).toMatch(/limit/i)
        expect(userFacingMessage('tool_error')).toMatch(/tool/i)
        expect(userFacingMessage('capability_mismatch')).toMatch(/client/i)
        expect(userFacingMessage('unknown')).toMatch(/wasn't able/i)
    })

    it('never contains raw infra detail', () => {
        // Sanitization invariant: messages must not mention docker, MCP, kafka, etc.
        for (const cat of [
            'transient_infra',
            'configuration',
            'quota_exhausted',
            'tool_error',
            'capability_mismatch',
            'unknown',
        ] as const) {
            const msg = userFacingMessage(cat)
            expect(msg.toLowerCase()).not.toMatch(/docker|kafka|redis|postgres|mcp|stack/i)
        }
    })
})

describe('NoopFailureNotifier', () => {
    it('returns without doing anything', async () => {
        const n = new NoopFailureNotifier()
        await expect(
            n.notify({ session: makeSession(null), application: APP, revision: REV, reason: 'x', category: 'unknown' })
        ).resolves.toBeUndefined()
    })
})

describe('TriggerAwareFailureNotifier', () => {
    function makeSub(): FailureNotifier & { notify: ReturnType<typeof vi.fn> } {
        return { notify: vi.fn(async () => undefined) } as unknown as FailureNotifier & {
            notify: ReturnType<typeof vi.fn>
        }
    }

    it('dispatches by trigger_metadata.kind', async () => {
        const slack = makeSub()
        const webhook = makeSub()
        const n = new TriggerAwareFailureNotifier({ slack, webhook })
        await n.notify({
            session: makeSession({ kind: 'slack', workspace_id: 'W', channel: 'C1', ts: 't', thread_ts: '123' }),
            application: APP,
            revision: REV,
            reason: 'x',
            category: 'unknown',
        })
        expect(slack.notify).toHaveBeenCalledTimes(1)
        expect(webhook.notify).not.toHaveBeenCalled()
    })

    it('no-ops when trigger_metadata is null', async () => {
        const slack = makeSub()
        const n = new TriggerAwareFailureNotifier({ slack })
        await n.notify({
            session: makeSession(null),
            application: APP,
            revision: REV,
            reason: 'x',
            category: 'unknown',
        })
        expect(slack.notify).not.toHaveBeenCalled()
    })

    it('no-ops when trigger_metadata.kind is unregistered', async () => {
        const slack = makeSub()
        const n = new TriggerAwareFailureNotifier({ slack })
        await n.notify({
            session: makeSession({ kind: 'chat' }),
            application: APP,
            revision: REV,
            reason: 'x',
            category: 'unknown',
        })
        await n.notify({
            session: makeSession({ kind: 'mcp' }),
            application: APP,
            revision: REV,
            reason: 'x',
            category: 'unknown',
        })
        expect(slack.notify).not.toHaveBeenCalled()
    })

    it('catches sub-notifier throws and logs at warn', async () => {
        const slack: FailureNotifier = {
            notify: vi.fn(async () => {
                throw new Error('boom')
            }),
        }
        const logger = { warn: vi.fn() }
        const n = new TriggerAwareFailureNotifier({ slack }, logger)
        await expect(
            n.notify({
                session: makeSession({ kind: 'slack', workspace_id: 'W', channel: 'C1', ts: 't', thread_ts: '123' }),
                application: APP,
                revision: REV,
                reason: 'x',
                category: 'unknown',
            })
        ).resolves.toBeUndefined()
        expect(logger.warn).toHaveBeenCalledTimes(1)
        expect(logger.warn.mock.calls[0]![1]).toBe('failure_notifier_dispatch_threw')
    })
})
