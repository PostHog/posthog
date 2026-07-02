/**
 * Unit tests for the pure-logic branches inside `approval.ts`. The PG-backed
 * end-to-end behaviour (intercept → upsert → wake → dispatch) is covered by
 * `agent-tests/src/cases/approval-gated.test.ts`; this file pins the model-
 * facing envelope shape.
 */

import { describe, expect, it } from 'vitest'

import {
    AgentSession,
    ApprovalRequest,
    ApprovalStore,
    EMPTY_USAGE_TOTAL,
    type TriggerMetadata,
    UpsertApprovalRequestInput,
    UpsertApprovalRequestResult,
} from '@posthog/agent-shared'

import { type ApprovalPolicy, dispatchApprovedResult, queueApprovalResult } from './approval'
import type { RealToolExecute } from './build-agent-tools'
import { resolveApprovedExecutor } from './mcp-tool-lookup'

const TEST_SESSION_ID = '00000000-0000-4000-8000-00000000fe01'
const TEST_APP_ID = '00000000-0000-4000-8000-00000000fa01'
const TEST_REV_ID = '00000000-0000-4000-8000-00000000fb01'

function makeSession(over: Partial<AgentSession> = {}): AgentSession {
    return {
        id: TEST_SESSION_ID,
        application_id: TEST_APP_ID,
        revision_id: TEST_REV_ID,
        team_id: 1,
        external_key: null,
        idempotency_key: null,
        trigger_metadata: null,
        state: 'running',
        principal: null,
        conversation: [{ role: 'user', content: 'hi', timestamp: 0 }],
        pending_inputs: [],
        retry_count: 0,
        acl: [],
        pending_elevation_requests: [],
        usage_total: { ...EMPTY_USAGE_TOTAL },
        created_at: '2026-06-16',
        updated_at: '2026-06-16',
        ...over,
    }
}

/**
 * Minimal stub: queueApprovalResult only calls `upsertQueued` + `findLatestByArgs`
 * on the happy path. The PG-backed wire path is covered by approval-gated e2e.
 */
function makeStubStore(): ApprovalStore {
    return {
        async upsertQueued(input: UpsertApprovalRequestInput): Promise<UpsertApprovalRequestResult> {
            return {
                request: {
                    id: input.id,
                    session_id: input.session_id,
                    application_id: input.application_id,
                    revision_id: input.revision_id,
                    team_id: input.team_id,
                    turn: input.turn,
                    tool_call_id: input.tool_call_id,
                    tool_name: input.tool_name,
                    proposed_args: input.proposed_args,
                    args_hash: Buffer.alloc(0),
                    assistant_message: input.assistant_message,
                    approver_scope: input.approver_scope,
                    state: 'queued',
                    decision_by: null,
                    decision_at: null,
                    decision_reason: null,
                    decided_args: null,
                    dispatch_outcome: null,
                    expires_at: input.expires_at,
                    created_at: input.expires_at,
                } as ApprovalRequest,
                deduped: false,
            }
        },
        async findLatestByArgs(): Promise<ApprovalRequest | null> {
            return null
        },
    } as unknown as ApprovalStore
}

const POLICY: ApprovalPolicy = {
    type: 'principal',
    allow_edit: false,
    ttl_ms: 60_000,
}

function parseEnvelope(text: string): { approval: Record<string, unknown> } {
    return JSON.parse(text) as { approval: Record<string, unknown> }
}

describe('queueApprovalResult: model-facing envelope', () => {
    it('includes a principal approver_hint + approval_url for the default (non-posthog-code) session', async () => {
        const store = makeStubStore()
        const out = await queueApprovalResult({
            approvals: store,
            buildApprovalUrl: (id) => `https://console.example.com/approvals?request=${id}`,
            session: makeSession(),
            revisionId: TEST_REV_ID,
            turn: 1,
            toolName: '@posthog/memory-write',
            toolCallId: 'tc-1',
            args: { note: 'apples' },
            policy: POLICY,
        })
        const envelope = parseEnvelope((out.content[0] as { text: string }).text)
        expect(envelope.approval).toMatchObject({
            state: 'queued',
            approver_hint: expect.stringMatching(/started this session/i),
            approval_url: expect.stringContaining('https://console.example.com/approvals?request='),
        })
    })

    it('uses an owner/admin approver_hint for an agent-type policy', async () => {
        const store = makeStubStore()
        const out = await queueApprovalResult({
            approvals: store,
            buildApprovalUrl: (id) => `https://console.example.com/approvals?request=${id}`,
            session: makeSession(),
            revisionId: TEST_REV_ID,
            turn: 1,
            toolName: '@posthog/memory-write',
            toolCallId: 'tc-1',
            args: { note: 'apples' },
            policy: { ...POLICY, type: 'agent' },
        })
        const envelope = parseEnvelope((out.content[0] as { text: string }).text)
        expect(envelope.approval).toMatchObject({
            state: 'queued',
            approver_hint: expect.stringMatching(/owner or admin/i),
        })
    })

    // The approval envelope used to suppress approver_hint + approval_url for
    // posthog-code (`client_kind`-gated). That gating is gone — the envelope
    // is now uniform across every trigger kind. Pin that contract by
    // exercising each TriggerMetadata variant + null.
    it.each<[string, TriggerMetadata | null]>([
        ['null trigger_metadata', null],
        ['chat with no declared client tools', { kind: 'chat' }],
        ['chat with declared client tools', { kind: 'chat', supported_client_tools: ['connect_mcp'] }],
        ['slack', { kind: 'slack', workspace_id: 'W', channel: 'C', ts: 't', thread_ts: 't' }],
        ['webhook', { kind: 'webhook' }],
        ['mcp', { kind: 'mcp' }],
        ['cron', { kind: 'cron', cron_name: 'daily', schedule: '0 9 * * *', fired_at: '2026-06-25T09:00:00Z' }],
    ])('includes approver_hint + approval_url for %s', async (_label, trigger_metadata) => {
        const store = makeStubStore()
        const out = await queueApprovalResult({
            approvals: store,
            buildApprovalUrl: (id) => `https://console.example.com/approvals?request=${id}`,
            session: makeSession({ trigger_metadata }),
            revisionId: TEST_REV_ID,
            turn: 1,
            toolName: '@posthog/memory-write',
            toolCallId: 'tc-1',
            args: { note: 'apples' },
            policy: POLICY,
        })
        const envelope = parseEnvelope((out.content[0] as { text: string }).text)
        expect(envelope.approval.approver_hint).not.toBeUndefined()
        expect(envelope.approval.approval_url).not.toBeUndefined()
    })
})

describe('dispatchApprovedResult: proxy-routed resume', () => {
    // A proxy connection gates `call_tool` on the underlying tool, so the
    // approval row is keyed `<prefix>__<remoteName>` with the call_tool args
    // stashed as proposed_args. On resume the driver must route that row back to
    // the connection's `call_tool` executor (via resolveApprovedExecutor) — a
    // plain `realExecute.get(row.tool_name)` misses it and drops the call.
    function makeProxyRow(over: Partial<ApprovalRequest> = {}): ApprovalRequest {
        return {
            id: 'req-proxy-1',
            session_id: TEST_SESSION_ID,
            application_id: TEST_APP_ID,
            revision_id: TEST_REV_ID,
            team_id: 1,
            turn: 1,
            tool_call_id: 'tc-9',
            tool_name: 'posthog__get-insights',
            proposed_args: { tool_name: 'get-insights', arguments: { limit: 5 } },
            args_hash: Buffer.alloc(0),
            assistant_message: null,
            approver_scope: null,
            state: 'approving',
            decision_by: 'u1',
            decision_at: null,
            decision_reason: null,
            decided_args: null,
            dispatch_outcome: null,
            expires_at: '2026-06-26',
            created_at: '2026-06-26',
            ...over,
        } as ApprovalRequest
    }

    function dispatchStore(): ApprovalStore & { dispatched: Array<{ id: string; outcome: unknown }> } {
        const dispatched: Array<{ id: string; outcome: unknown }> = []
        return {
            dispatched,
            async markDispatched(id: string, outcome: unknown): Promise<void> {
                dispatched.push({ id, outcome })
            },
        } as unknown as ApprovalStore & { dispatched: Array<{ id: string; outcome: unknown }> }
    }

    it('replays the approved proxy call through the connection call_tool executor', async () => {
        const seen: Array<{ id: string; args: Record<string, unknown> }> = []
        const callToolExec: RealToolExecute = async (id, args) => {
            seen.push({ id, args })
            return { content: [{ type: 'text' as const, text: 'ok' }], details: { output: { ran: true } } }
        }
        const realExecute = new Map<string, RealToolExecute>([['posthog__call_tool', callToolExec]])
        const proxyCallTools = new Map<string, unknown>([['posthog__call_tool', {}]])
        const row = makeProxyRow()
        const store = dispatchStore()

        const d = await dispatchApprovedResult({
            approvals: store,
            realExecute: resolveApprovedExecutor(row.tool_name, realExecute, proxyCallTools),
            row,
        })

        expect(d.isError).toBe(false)
        // The call_tool executor ran with the row's stored call_tool args (the
        // remote tool + its arguments), i.e. the real call replayed.
        expect(seen).toEqual([{ id: 'tc-9', args: { tool_name: 'get-insights', arguments: { limit: 5 } } }])
        expect(store.dispatched[0]?.outcome).toEqual({ result: { ran: true } })
    })

    it('the old direct lookup (the bug) drops the call with a synthetic "unknown tool"', async () => {
        const realExecute = new Map<string, RealToolExecute>([
            ['posthog__call_tool', async () => ({ content: [], details: {} })],
        ])
        const row = makeProxyRow()

        const d = await dispatchApprovedResult({
            approvals: dispatchStore(),
            // What the driver did before: a plain lookup by the re-keyed name.
            realExecute: realExecute.get(row.tool_name),
            row,
        })

        expect(d.isError).toBe(true)
        expect(d.error).toBe('native tool unknown: posthog__get-insights')
    })
})
