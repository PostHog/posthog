/**
 * Per-asker authorization for approval-gated tools. Reads the sender of
 * the most recent user message in the session conversation and resolves
 * "is this asker themselves in the approver scope?" — if so, the dispatcher
 * can dispatch the tool directly instead of queueing for someone else to
 * approve.
 *
 * Fast-path scopes (skip the queue, run the real tool):
 *   - `team_admins` — the original B.2 v0 scope. Resolution:
 *     - `sender.kind === 'slack'`: `sender.id` is an `agent_user.id`. Read the
 *       PostHog subject (uuid) the principal proved via an identity-establishing
 *       link, then check OrganizationMembership for `level >= ADMIN`. (Slated
 *       for rework alongside the identity model — kept minimal here.)
 *     - Other kinds: not authorised for v0. PAT-based self-authorisation
 *       (chat /run with an admin's token) is a sensible follow-up but adds
 *       a second resolution path that step 3 doesn't need to demo the
 *       Slack scenario.
 *
 * NOT a fast-path:
 *   - `session_principal` — marks "the session owner is the approver", but the
 *     owner being the *asker* is not consent to the specific gated call the model
 *     emitted, so it never self-authorises here; it always queues for an explicit
 *     out-of-band human decision. (Adopts master's "approval bypass for
 *     session-principal tools" fix. The team-admin resolution still uses the
 *     branch's established-subject model rather than master's `posthog_user_id` —
 *     reconciling the two is a deliberate follow-up.)
 */

import type { Pool } from 'pg'

import { ConversationMessage, IdentityCredentialStore, SessionPrincipal } from '@posthog/agent-shared'

/** PostHog's `OrganizationMembership.Level` values — keep in sync with the Django enum. */
const ADMIN_LEVEL = 8

/**
 * The check the dispatcher runs against the active session conversation.
 * Returns true when the most-recent user turn's sender satisfies a fast-path
 * scope (today: `team_admins` only). Returning false defers to the normal
 * queue path; the model never sees the difference.
 *
 * `sessionPrincipal` (the auth-time identity on the session row) is accepted
 * for signature/forward-compatibility but is NOT consumed: `session_principal`
 * is deliberately not a self-authorising fast-path, so a sender↔principal match
 * never clears the gate here.
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
    // `sessionPrincipal` (4th arg) is intentionally not consumed: `session_principal`
    // is NOT a self-authorising fast-path. The owner being the *asker* is not consent
    // to the specific gated call the model emitted — a prompt injection in content the
    // agent read could steer a destructive call while the legitimate owner is still the
    // last sender. So it always defers to the queue; only `team_admins` fast-paths.
    // (Adopts master's "approval bypass for session-principal tools" fix. Reconciling
    // team-admin resolution — PostHog `posthog_user_id` vs the established subject — is
    // a deliberate follow-up; the approvals system needs a broader rethink.)
    return async (conversation, teamId, approverScope) => {
        if (!approverScope.includes('team_admins')) {
            return false
        }
        const sender = findLastUserSender(conversation)
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
