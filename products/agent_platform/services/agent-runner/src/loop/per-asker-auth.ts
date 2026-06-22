/**
 * Per-asker authorization for approval-gated tools. Reads the sender of
 * the most recent user message in the session conversation and resolves
 * "is this asker themselves in the approver scope?" — if so, the dispatcher
 * can dispatch the tool directly instead of queueing for someone else to
 * approve.
 *
 * Scopes supported in v0:
 *   - `team_admins` — the original B.2 v0 scope. Resolution:
 *     - `sender.kind === 'slack'`: `sender.id` is an `agent_user.id`. Read the
 *       PostHog subject (uuid) the principal proved via an identity-establishing
 *       link, then check OrganizationMembership for `level >= ADMIN`. (Slated
 *       for rework alongside the identity model — kept minimal here.)
 *     - Other kinds: not authorised for v0. PAT-based self-authorisation
 *       (chat /run with an admin's token) is a sensible follow-up but adds
 *       a second resolution path that step 3 doesn't need to demo the
 *       Slack scenario.
 *   - `session_principal` (PR 7) — the session-owner-self-authorise case.
 *     Matches the most-recent user-turn sender against `session.principal`
 *     (auth-time identity stored on the session row) using the same strict
 *     `principalsMatch` comparison the trigger edge uses for /send. Stable
 *     across resume — a second user posting to a resumed session can't
 *     bypass the gate by being whoever-spoke-last. Per-asker fast-path
 *     only; queued-approval routing to the session principal widens later.
 */

import type { Pool } from 'pg'

import { ConversationMessage, IdentityCredentialStore, principalsMatch, SessionPrincipal } from '@posthog/agent-shared'

/** PostHog's `OrganizationMembership.Level` values — keep in sync with the Django enum. */
const ADMIN_LEVEL = 8

/**
 * The check the dispatcher runs against the active session conversation.
 * Returns true when the most-recent user turn's sender satisfies one of the
 * scopes in `approverScope`. Returning false defers to the normal queue
 * path; the model never sees the difference.
 *
 * `sessionPrincipal` is the auth-time identity persisted on the session row
 * — used for the `session_principal` scope match. Anonymous principals
 * (public agents) are explicitly excluded: the public verifier stores
 * `{ kind: 'anonymous' }` — not null — in the session row, and
 * `principalsMatch` returns true for any two anonymous principals, which
 * would let every caller bypass the gate. The `session_principal` scope is
 * only meaningful for authenticated sessions with a unique identity.
 */
export type IsAskerInApproverScope = (
    conversation: ConversationMessage[],
    teamId: number,
    approverScope: ReadonlyArray<string>,
    sessionPrincipal: SessionPrincipal | null
) => Promise<boolean>

export interface MakePerAskerAuthDeps {
    credentials: IdentityCredentialStore
    posthogDb: Pool
}

/** Production factory — closes over the credential store + posthog DB pool. */
export function makePerAskerAuth(deps: MakePerAskerAuthDeps): IsAskerInApproverScope {
    return async (conversation, teamId, approverScope, sessionPrincipal) => {
        const sender = findLastUserSender(conversation)
        // `session_principal` is a pure equality check against the
        // auth-time principal on the session row — no DB roundtrip. Cheap;
        // check first so we don't burn a posthog DB query on every gated
        // call for a concierge-style spec. Anonymous principals are excluded:
        // `principalsMatch` treats any two anonymous principals as equal, so on
        // a public agent every caller would self-authorise the gate.
        if (approverScope.includes('session_principal') && sessionPrincipal && sessionPrincipal.kind !== 'anonymous') {
            if (sender && principalsMatch(sessionPrincipal, sender)) {
                return true
            }
        }
        if (!approverScope.includes('team_admins')) {
            return false
        }
        if (!sender) {
            return false
        }
        const subject = await resolveEstablishedSubject(sender, deps.credentials)
        if (subject === null) {
            return false
        }
        return isTeamAdmin(deps.posthogDb, subject, teamId)
    }
}

/**
 * Walk the conversation back-to-front looking for the most recent user turn
 * with a `sender`. System-synthesised user messages (approval-decided
 * wakes, sweep-expired wakes) intentionally leave `sender` undefined and
 * are skipped — they aren't human asker actions.
 */
export function findLastUserSender(conversation: ConversationMessage[]): SessionPrincipal | null {
    for (let i = conversation.length - 1; i >= 0; i--) {
        const m = conversation[i]
        if (m.role !== 'user') {
            continue
        }
        if (m.sender) {
            return m.sender
        }
    }
    return null
}

async function resolveEstablishedSubject(
    sender: SessionPrincipal,
    credentials: IdentityCredentialStore
): Promise<string | null> {
    if (sender.kind !== 'slack' || !sender.agent_user_id) {
        return null
    }
    // The PostHog user uuid the principal proved via an identity-establishing
    // link (e.g. the managed posthog provider). Null if they never linked.
    return credentials.getEstablishedSubject(sender.agent_user_id)
}

async function isTeamAdmin(pool: Pool, subjectUuid: string, teamId: number): Promise<boolean> {
    const r = await pool.query<{ one: number }>(
        // Map the proven subject (posthog_user.uuid) to its membership in one
        // hop. OrganizationMembership.Level: ADMIN=8, OWNER=15. The team belongs
        // to an organization; the membership scopes to that organization.
        `SELECT 1 AS one
         FROM posthog_user u
         JOIN posthog_organizationmembership om ON om.user_id = u.id
         JOIN posthog_team t ON t.organization_id = om.organization_id
         WHERE u.uuid = $1 AND t.id = $2 AND om.level >= $3
         LIMIT 1`,
        [subjectUuid, teamId, ADMIN_LEVEL]
    )
    return (r.rowCount ?? 0) > 0
}
