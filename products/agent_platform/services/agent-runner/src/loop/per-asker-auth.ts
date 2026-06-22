/**
 * Per-asker authorization for approval-gated tools. Reads the sender of
 * the most recent user message in the session conversation and resolves
 * "is this asker themselves in the approver scope?" — if so, the dispatcher
 * can dispatch the tool directly instead of queueing for someone else to
 * approve.
 *
 * Fast-path scopes (skip the queue, run the real tool):
 *   - `team_admins` — the original B.2 v0 scope. Resolution:
 *     - `sender.kind === 'slack'`: `sender.id` is an `agent_user.id`. Look
 *       up the row, read its `posthog_user_id`, check OrganizationMembership
 *       for `level >= ADMIN`.
 *     - Other kinds: not authorised for v0. PAT-based self-authorisation
 *       (chat /run with an admin's token) is a sensible follow-up but adds
 *       a second resolution path that step 3 doesn't need to demo the
 *       Slack scenario.
 *
 * NOT a fast-path scope:
 *   - `session_principal` — marks "the session owner is the approver", but
 *     the owner being the *asker* is NOT evidence they consented to the
 *     specific gated call the model emitted. Content the agent reads (fetched
 *     docs, MCP/tool output, another agent's bundle) can carry a prompt
 *     injection that steers the model into a destructive gated call while the
 *     most-recent user-turn sender is still the legitimate owner — so a
 *     sender↔principal match would silently auto-execute an action the human
 *     never decided on. `session_principal` therefore always queues for an
 *     explicit, out-of-band human decision; it never short-circuits `real(...)`.
 *     The scope is still persisted on the queued row (`approver_scope`) so
 *     decision-side routing — letting the session owner, not only a team
 *     admin, clear the queued approval — can land as a follow-up.
 *     (Fixes the "approval bypass for session-principal tools" review finding.)
 */

import type { Pool } from 'pg'

import { ConversationMessage, IdentityStore, SessionPrincipal } from '@posthog/agent-shared'

/** PostHog's `OrganizationMembership.Level` values — keep in sync with the Django enum. */
const ADMIN_LEVEL = 8

/**
 * The check the dispatcher runs against the active session conversation.
 * Returns true when the most-recent user turn's sender satisfies a fast-path
 * scope in `approverScope` (today: `team_admins` only). Returning false
 * defers to the normal queue path; the model never sees the difference.
 *
 * `sessionPrincipal` (the auth-time identity persisted on the session row) is
 * accepted for forward compatibility with decision-side approver routing but
 * is NOT consumed by the v0 check: `session_principal` is deliberately not a
 * self-authorising fast-path scope (see the module doc), so a sender↔principal
 * match never clears the gate here.
 */
export type IsAskerInApproverScope = (
    conversation: ConversationMessage[],
    teamId: number,
    approverScope: ReadonlyArray<string>,
    sessionPrincipal: SessionPrincipal | null
) => Promise<boolean>

export interface MakePerAskerAuthDeps {
    identities: IdentityStore
    posthogDb: Pool
}

/** Production factory — closes over the identity store + posthog DB pool. */
export function makePerAskerAuth(deps: MakePerAskerAuthDeps): IsAskerInApproverScope {
    // `sessionPrincipal` (4th arg) is intentionally not destructured: the only
    // fast-path scope is `team_admins`. `session_principal` is NOT a
    // self-authorising fast-path — it always defers to the queue so a prompt
    // injection that the session owner unwittingly relays can't auto-execute a
    // gated call. See the module doc.
    return async (conversation, teamId, approverScope) => {
        if (!approverScope.includes('team_admins')) {
            return false
        }
        const sender = findLastUserSender(conversation)
        if (!sender) {
            return false
        }
        const posthogUserId = await resolvePosthogUserId(sender, deps.identities)
        if (posthogUserId === null) {
            return false
        }
        return isTeamAdmin(deps.posthogDb, posthogUserId, teamId)
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

async function resolvePosthogUserId(sender: SessionPrincipal, identities: IdentityStore): Promise<number | null> {
    if (sender.kind !== 'slack' || !sender.agent_user_id) {
        return null
    }
    const agentUser = await identities.getById(sender.agent_user_id)
    if (!agentUser || agentUser.posthog_user_id == null) {
        return null
    }
    return agentUser.posthog_user_id
}

async function isTeamAdmin(pool: Pool, posthogUserId: number, teamId: number): Promise<boolean> {
    const r = await pool.query<{ one: number }>(
        // OrganizationMembership.Level: ADMIN=8, OWNER=15. The team belongs
        // to an organization; the membership scopes to that organization.
        `SELECT 1 AS one
         FROM posthog_organizationmembership om
         JOIN posthog_team t ON t.organization_id = om.organization_id
         WHERE om.user_id = $1 AND t.id = $2 AND om.level >= $3
         LIMIT 1`,
        [posthogUserId, teamId, ADMIN_LEVEL]
    )
    return (r.rowCount ?? 0) > 0
}
