/**
 * Unit tests for the per-asker authorisation helper. The PostHog DB call is
 * stubbed; the contract under test is "does the helper correctly read the
 * most recent user-turn sender and resolve their authorisation."
 *
 * The credential store is the real `PgIdentityCredentialStore` against the test
 * DB — same impl prod runs. A Slack principal authorises as a team admin only
 * when they've linked an identity-establishing credential whose `subject` (the
 * proven PostHog user uuid) maps to an admin membership. Per-test reset keeps
 * cases isolated.
 */

import { Pool } from 'pg'

import { ConversationMessage, PgIdentityCredentialStore, SessionPrincipal } from '@posthog/agent-shared'
import { reset } from '@posthog/agent-shared/testing'

import { findLastUserSender, makePerAskerAuth } from './per-asker-auth'

const TEST_DB_URL =
    process.env.AGENT_TEST_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue_test'

// 32-byte UTF-8 Fernet key — matches the harness key the other store tests use.
const ENC_KEY = '01234567890123456789012345678901'
const APP_ID = '00000000-0000-4000-8000-00000000aa01'
// Stable agent_user ids (uuid column) we stamp onto conversation senders.
const CAROL = '00000000-0000-4000-8000-0000000000c1'
const EXTERNAL = '00000000-0000-4000-8000-0000000000e1'

let pool: Pool

beforeAll(() => {
    pool = new Pool({ connectionString: TEST_DB_URL })
})

afterAll(async () => {
    await pool.end()
})

beforeEach(async () => {
    await reset({ databaseUrl: TEST_DB_URL })
})

function userMsg(content: string, sender?: SessionPrincipal): ConversationMessage {
    return { role: 'user', content, timestamp: Date.now(), sender }
}

function assistantMsg(text: string): ConversationMessage {
    return {
        role: 'assistant',
        content: [{ type: 'text', text }],
        timestamp: Date.now(),
    }
}

function credentials(): PgIdentityCredentialStore {
    return new PgIdentityCredentialStore(pool, { encryptionSaltKeys: ENC_KEY })
}

/** Link an identity-establishing credential (subject = proven posthog uuid). */
async function linkSubject(store: PgIdentityCredentialStore, agentUserId: string, subject: string): Promise<void> {
    await store.put({
        teamId: 7,
        applicationId: APP_ID,
        agentUserId,
        provider: 'posthog',
        credential: { access_token: 'tok' },
        subject,
    })
}

function slackSender(agentUserId: string): SessionPrincipal {
    return { kind: 'slack', workspace_id: 'T_7', slack_user_id: agentUserId, agent_user_id: agentUserId }
}

// Stub matching the Pool surface `isTeamAdmin` uses — keyed on (subject uuid, team).
function fakePosthogDb(admins: Array<{ subject: string; team_id: number }>): import('pg').Pool {
    return {
        async query(_sql: string, params: unknown[]) {
            const [subject, teamId] = params as [string, number]
            const found = admins.find((a) => a.subject === subject && a.team_id === teamId)
            return found ? { rowCount: 1, rows: [{ one: 1 }] } : { rowCount: 0, rows: [] }
        },
    } as unknown as import('pg').Pool
}

describe('findLastUserSender', () => {
    it('returns the sender of the most recent user message that has one', () => {
        const sender = slackSender('au-bob')
        const sender2 = slackSender('au-carol')
        const conv = [userMsg('first', sender), assistantMsg('reply'), userMsg('second', sender2)]
        expect(findLastUserSender(conv)).toEqual(sender2)
    })

    it('skips synthetic user messages with no sender (sweep wakes, etc.)', () => {
        const sender = slackSender('au-carol')
        const conv = [userMsg('alice asked', sender), assistantMsg('replying'), userMsg('synthetic wake')]
        expect(findLastUserSender(conv)).toEqual(sender)
    })

    it('returns null when no user message has a sender', () => {
        expect(findLastUserSender([userMsg('legacy message, no sender')])).toBeNull()
    })

    it('returns null for an empty conversation', () => {
        expect(findLastUserSender([])).toBeNull()
    })
})

describe('makePerAskerAuth', () => {
    it('returns true when the asker linked a posthog subject that is a team admin', async () => {
        const store = credentials()
        await linkSubject(store, CAROL, 'carol-uuid')
        const isAuthed = makePerAskerAuth({
            credentials: store,
            posthogDb: fakePosthogDb([{ subject: 'carol-uuid', team_id: 7 }]),
        })
        expect(await isAuthed([userMsg('do the thing', slackSender(CAROL))], 7, ['team_admins'], null)).toBe(true)
    })

    it('returns false when the linked subject is an admin on another team, not this one', async () => {
        const store = credentials()
        await linkSubject(store, CAROL, 'carol-uuid')
        const isAuthed = makePerAskerAuth({
            credentials: store,
            posthogDb: fakePosthogDb([{ subject: 'carol-uuid', team_id: 7 }]),
        })
        // Carol is admin on team 7, but the question is about team 99.
        expect(await isAuthed([userMsg('do the thing', slackSender(CAROL))], 99, ['team_admins'], null)).toBe(false)
    })

    it('returns false when the sender has no linked identity (never OAuth-linked)', async () => {
        const isAuthed = makePerAskerAuth({
            credentials: credentials(),
            posthogDb: fakePosthogDb([{ subject: 'carol-uuid', team_id: 7 }]),
        })
        expect(await isAuthed([userMsg('ghost asker', slackSender(EXTERNAL))], 7, ['team_admins'], null)).toBe(false)
    })

    it('returns false for a capability-only link (no subject stamped)', async () => {
        // An external Slack member linked e.g. a `dogs` credential — that link
        // carries no subject, so getEstablishedSubject returns null.
        const store = credentials()
        await store.put({
            teamId: 7,
            applicationId: APP_ID,
            agentUserId: EXTERNAL,
            provider: 'dogs',
            credential: { access_token: 'tok' },
        })
        const isAuthed = makePerAskerAuth({
            credentials: store,
            posthogDb: fakePosthogDb([{ subject: 'whatever', team_id: 7 }]),
        })
        expect(await isAuthed([userMsg('external request', slackSender(EXTERNAL))], 7, ['team_admins'], null)).toBe(
            false
        )
    })

    it('returns false for non-slack principals (service, internal, etc.)', async () => {
        // PAT-based self-authorisation is a sensible follow-up but isn't in v0.
        const isAuthed = makePerAskerAuth({
            credentials: credentials(),
            posthogDb: fakePosthogDb([{ subject: 'carol-uuid', team_id: 7 }]),
        })
        const conv = [userMsg('via pat', { kind: 'service', team_id: 7, id: 'pat-carol' })]
        expect(await isAuthed(conv, 7, ['team_admins'], null)).toBe(false)
    })

    it('returns false when no user-turn carries a sender (legacy rows)', async () => {
        const isAuthed = makePerAskerAuth({ credentials: credentials(), posthogDb: fakePosthogDb([]) })
        expect(await isAuthed([userMsg('legacy'), userMsg('also legacy')], 7, ['team_admins'], null)).toBe(false)
    })

    it('returns false when the approver scope does not include team_admins or session_principal', async () => {
        const isAuthed = makePerAskerAuth({ credentials: credentials(), posthogDb: fakePosthogDb([]) })
        const conv = [userMsg('q', slackSender('au-id'))]
        // `session_owner` isn't in the v0 enum (zod would reject it upstream);
        // we still fail closed if a stray scope slips through.
        expect(await isAuthed(conv, 7, ['session_owner'], null)).toBe(false)
        expect(await isAuthed(conv, 7, [], null)).toBe(false)
    })

    describe('session_principal scope (PR 7 — concierge fast-path)', () => {
        const alice: SessionPrincipal = { kind: 'posthog', user_id: 'alice', team_id: 7 }
        const bob: SessionPrincipal = { kind: 'posthog', user_id: 'bob', team_id: 7 }

        it('returns true when the session principal matches the most recent user-turn sender', async () => {
            // Fast-path authorises without touching the posthog DB (the fake's
            // query throws if called).
            const isAuthed = makePerAskerAuth({
                credentials: credentials(),
                posthogDb: {
                    async query() {
                        throw new Error('should not hit posthog DB on the session_principal fast path')
                    },
                } as unknown as import('pg').Pool,
            })
            expect(await isAuthed([userMsg('promote it', alice)], 7, ['session_principal'], alice)).toBe(true)
        })

        it('returns false when the last sender is a different principal than the session owner', async () => {
            const isAuthed = makePerAskerAuth({ credentials: credentials(), posthogDb: fakePosthogDb([]) })
            expect(await isAuthed([userMsg('promote it', bob)], 7, ['session_principal'], alice)).toBe(false)
        })

        it('returns false when sessionPrincipal is null (public agent — nothing to compare against)', async () => {
            const isAuthed = makePerAskerAuth({ credentials: credentials(), posthogDb: fakePosthogDb([]) })
            expect(await isAuthed([userMsg('promote it', alice)], 7, ['session_principal'], null)).toBe(false)
        })

        it('returns false for anonymous principals (public agent — every caller would otherwise self-authorise)', async () => {
            const anon: SessionPrincipal = { kind: 'anonymous' }
            const isAuthed = makePerAskerAuth({ credentials: credentials(), posthogDb: fakePosthogDb([]) })
            expect(await isAuthed([userMsg('promote it', anon)], 7, ['session_principal'], anon)).toBe(false)
        })

        it('falls through to team_admins when session_principal does not match but team_admins is in scope', async () => {
            // Mixed-scope policy: session principal OR team admin. The session
            // principal slot doesn't match (bob's session vs an admin sender),
            // so we fall through and resolve team_admins via the subject path.
            const store = credentials()
            await linkSubject(store, CAROL, 'admin-uuid')
            const isAuthed = makePerAskerAuth({
                credentials: store,
                posthogDb: fakePosthogDb([{ subject: 'admin-uuid', team_id: 7 }]),
            })
            const conv = [userMsg('approve it', slackSender(CAROL))]
            expect(await isAuthed(conv, 7, ['session_principal', 'team_admins'], bob)).toBe(true)
        })
    })
})
