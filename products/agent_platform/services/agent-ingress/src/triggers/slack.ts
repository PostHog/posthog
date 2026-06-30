/**
 * Slack events trigger.
 *
 * POST /agents/<slug>/slack/events takes Slack's events-api payload; POST
 * /agents/<slug>/slack/interactivity takes button clicks. Both routes are
 * `slack_signing` — the mount guard resolves the agent, looks up the per-agent
 * signing secret, and verifies `X-Slack-Signature` before the handler runs.
 * The handler therefore sees an already-verified request and enqueues an
 * AgentSession using thread_ts as the externalKey so repeated messages in the
 * same thread resume a single agent session.
 */

import { z } from 'zod'

import { createLogger } from '@posthog/agent-shared'

const log = createLogger('slack-trigger')

import {
    AgentApplication,
    AgentRevision,
    applyApprovalDecision,
    decodeApprovalActionValue,
    effectiveApprovalType,
    principalsMatch,
    SessionPrincipal,
    SLACK_BOT_TOKEN_KEY,
} from '@posthog/agent-shared'

import { applyElevationDecline, applyElevationGrant, authorizeGrant } from '../enqueue/acl'
import { enqueueOrResume } from '../enqueue/enqueue'
import { getOwnedSession } from './session-access'
import { verifySlackSignature } from './slack-signature'
import { SlackEventBodySchema } from './slack.schemas'
import type { RouteCtx, TriggerDeps, TriggerModule } from './types'

// Re-exported for backwards compatibility — the guard (mount.ts) is the
// enforcement point, but the helper stays available on the package surface.
export { verifySlackSignature }

async function slackEventsHandler(ctx: RouteCtx): Promise<void> {
    const { req, res, deps, resolved } = ctx
    // Signature already verified by the slack_signing guard.
    const slackSpecTrigger = resolved.revision.spec.triggers.find((t) => t.type === 'slack')
    const body = req.body as {
        type?: string
        challenge?: string
        event?: SlackEvent
        event_id?: string
        // `message` events carry the workspace here, not on `event.team`.
        team_id?: string
    }
    if (body.type === 'url_verification') {
        res.json({ challenge: body.challenge })
        return
    }
    const event = body.event
    // Accept both `message` (channel messages the bot is a member of) and
    // `app_mention` (someone @-mentioned the bot). Slack delivers the latter
    // even when a workspace only subscribed to mentions, and the spec's
    // `slack.config.mention_only` flag implies the ingress was always meant
    // to handle it.
    if (!event || (event.type !== 'message' && event.type !== 'app_mention') || event.bot_id) {
        res.json({ ok: true })
        return
    }

    // Workspace trust check. trusted_workspaces is required in the spec: an
    // array gates on membership; `"*"` opens to any workspace.
    const slackConfig =
        slackSpecTrigger && 'config' in slackSpecTrigger
            ? (slackSpecTrigger.config as {
                  trusted_workspaces?: string[] | '*'
                  mention_only?: boolean
                  auto_resume_threads?: boolean
                  allow_workspace_participants?: boolean
                  allow_direct_messages?: boolean
                  ack_reaction?: string
              })
            : ({} as {
                  trusted_workspaces?: string[] | '*'
                  mention_only?: boolean
                  auto_resume_threads?: boolean
                  allow_workspace_participants?: boolean
                  allow_direct_messages?: boolean
                  ack_reaction?: string
              })
    const trusted = slackConfig.trusted_workspaces
    // message events lack event.team; fall back to the envelope team_id.
    const workspaceId = event.team ?? body.team_id ?? 'unknown'
    if (trusted !== '*' && (!Array.isArray(trusted) || !trusted.includes(workspaceId))) {
        // The rejected workspace id is otherwise only in the 403 body — surface
        // it (plus the configured allowlist) so "why is Slack getting a 403?"
        // is answerable from the logs alone.
        log.warn(
            { slug: resolved.application.slug, workspace: workspaceId, trusted_workspaces: trusted ?? null },
            'slack_event_rejected_workspace_not_trusted'
        )
        res.status(403).json({ error: 'workspace_not_trusted', workspace: workspaceId })
        return
    }

    // mention_only / auto_resume_threads gate. Run BEFORE identity resolution +
    // the slack→posthog bridge so we don't pay an identity-store write per
    // dropped event when the bot is in a busy channel.
    //
    // Semantics:
    //   - app_mention → always accepted (explicit @ to the bot).
    //   - message + mention_only=false → accepted (back-compat with bots that
    //     watch whole channels by design).
    //   - message + mention_only=true + auto_resume_threads=false → dropped.
    //   - message + mention_only=true + auto_resume_threads=true → accepted ONLY
    //     when thread_ts matches an existing session's external_key.
    const isAppMention = event.type === 'app_mention'
    const mentionOnly = slackConfig.mention_only ?? false
    const autoResumeThreads = slackConfig.auto_resume_threads ?? false
    // When set, any user in a trusted workspace may advance an open thread —
    // waive the per-session owner ACL on resume. The trusted_workspaces gate
    // above already authorized the workspace.
    const allowWorkspaceParticipants = slackConfig.allow_workspace_participants ?? false
    const ackReaction = slackConfig.ack_reaction
    // DM surface. `im` = 1:1, `mpim` = group DM. A DM is inherently directed at
    // the bot (there's no @-mention in a 1:1), so it bypasses `mention_only`.
    const allowDirectMessages = slackConfig.allow_direct_messages ?? false
    const isDm = event.channel_type === 'im' || event.channel_type === 'mpim'
    // A DM arriving while the surface isn't opted in must not be silently
    // processed — drop it with a structured reason.
    if (isDm && !allowDirectMessages) {
        log.info(
            { slug: resolved.application.slug, channel: event.channel, channel_type: event.channel_type },
            'slack_event_dropped_dm_not_enabled'
        )
        res.json({ ok: true, dropped: 'dm_not_enabled' })
        return
    }
    // We need `externalKey` for both the gate and the enqueue below; compute once.
    // DMs have no thread, so they key per-channel — one rolling session per DM
    // conversation. Channels/groups stay thread-scoped.
    const externalKey = isDm ? `slack:${event.channel}` : `slack:${event.channel}:${event.thread_ts ?? event.ts}`
    // For non-mention events: track whether we're accepting because the message
    // is a reply in a thread the bot already owns. The seed message surfaces
    // this so the model can judge whether the user is actually talking to it.
    let resumedOwnedThread = false
    log.debug(
        {
            slug: resolved.application.slug,
            event_type: event.type,
            is_app_mention: isAppMention,
            channel: event.channel,
            thread_ts: event.thread_ts ?? null,
            mention_only: mentionOnly,
            auto_resume_threads: autoResumeThreads,
            is_dm: isDm,
            ack_reaction: ackReaction ?? null,
        },
        'slack_event_received'
    )
    if (!isAppMention && !isDm && mentionOnly) {
        if (!autoResumeThreads || !event.thread_ts) {
            log.info(
                { slug: resolved.application.slug, channel: event.channel, ts: event.ts },
                'slack_event_dropped_mention_only'
            )
            res.json({ ok: true, dropped: 'mention_only' })
            return
        }
        // Mention-only continuity is revision-scoped: a mention into a thread
        // whose only owned session is on another revision must not
        // short-circuit. Same scope as `enqueueOrResume`.
        const existing = await deps.queue.findByExternalKey(resolved.application.id, externalKey, resolved.revision.id)
        if (!existing) {
            log.info(
                { slug: resolved.application.slug, channel: event.channel, thread_ts: event.thread_ts },
                'slack_event_dropped_no_owned_thread'
            )
            res.json({ ok: true, dropped: 'mention_only_no_owned_thread' })
            return
        }
        resumedOwnedThread = true
    }

    // Fire-and-forget ack reaction. Posted to Slack now — before identity
    // resolution + enqueue — so the user sees the emoji within Slack's 3s ack
    // window. Fails open: a revoked/missing bot token, a slack.com 5xx, an
    // `already_reacted`, or a missing channel must NOT break the handler.
    if (ackReaction) {
        void postAckReaction(deps, resolved.application, resolved.revision, {
            channel: event.channel,
            ts: event.ts,
            name: ackReaction,
        }).catch((err) => {
            log.warn(
                {
                    slug: resolved.application.slug,
                    channel: event.channel,
                    ts: event.ts,
                    reaction: ackReaction,
                    err: err instanceof Error ? err.message : String(err),
                },
                'ack_reaction_threw'
            )
        })
    } else {
        log.debug({ slug: resolved.application.slug }, 'ack_reaction_not_configured')
    }

    // Identity resolution: same (workspace, user) tuple resolves to the same
    // AgentUser across sessions.
    const principalId = `${workspaceId}:${event.user}`
    let agentUserId = principalId
    if (deps.identities) {
        const agentUser = await deps.identities.findOrCreate({
            team_id: resolved.application.team_id,
            application_id: resolved.application.id,
            principal_kind: 'slack',
            principal_id: principalId,
            metadata: { workspace: workspaceId, slack_user: event.user },
        })
        agentUserId = agentUser.id
    }

    const slackPrincipal: SessionPrincipal = {
        kind: 'slack',
        workspace_id: workspaceId,
        slack_user_id: event.user,
        agent_user_id: agentUserId,
    }
    // Embed the Slack envelope context in the seed message so the model knows
    // which channel/ts/thread_ts to use when calling Slack APIs.
    const slackContext = [
        `[slack]`,
        `channel: ${event.channel}`,
        `ts: ${event.ts}`,
        `thread_ts: ${event.thread_ts ?? event.ts}`,
        `workspace: ${workspaceId}`,
        `user: ${event.user}`,
        `mention: ${isAppMention ? 'true' : 'false'}`,
        `dm: ${isDm ? 'true' : 'false'}`,
        ...(resumedOwnedThread ? ['resumed_owned_thread: true'] : []),
        ``,
        event.text ?? '',
    ].join('\n')
    const outcome = await enqueueOrResume(
        { queue: deps.queue },
        {
            application: resolved.application,
            revision: resolved.revision,
            externalKey,
            // (channel, ts) = one message: collapses app_mention + message.* and
            // Slack retries (same ts, distinct event_ids) into a single turn.
            idempotencyKey: `slack:msg:${event.channel}:${event.ts}`,
            seed: { role: 'user', content: slackContext, timestamp: Date.now(), sender: slackPrincipal },
            principal: slackPrincipal,
            trigger: 'slack',
            // Owner-only by default; when the agent opts into workspace-wide
            // participation, any trusted-workspace user (already gated above)
            // may advance the thread.
            bypassOwnerAcl: allowWorkspaceParticipants,
            requesterDisplay: `slack:${workspaceId}:${event.user}`,
            // Stash the originating thread coordinates so the runner can post a
            // sanitized failure reply if the session dies before answering.
            triggerMetadata: {
                kind: 'slack',
                workspace_id: workspaceId,
                channel: event.channel,
                ts: event.ts,
                thread_ts: event.thread_ts ?? event.ts,
            },
        }
    )
    if (outcome.kind === 'elevation_required') {
        // Owner-only thread: a different user posted into a session they don't
        // own. The message is parked as an elevation request; tell them
        // in-thread why nothing happened. Awaited so the reply lands before we
        // ack, but error-swallowed so it can never break the 200 Slack needs.
        await postThreadMessage(deps, resolved.application, resolved.revision, {
            channel: event.channel,
            thread_ts: event.thread_ts ?? event.ts,
            text:
                'I can only act on messages from the person who started this thread. ' +
                '@-mention me in a new message to start your own.',
        })
        res.json({
            ok: true,
            session_id: outcome.sessionId,
            resumed: false,
            elevation_required: true,
            elevation_request_id: outcome.elevationRequestId,
            owner_display: outcome.existingPrincipalDisplay,
        })
        return
    }
    res.json({ ok: true, session_id: outcome.sessionId, resumed: outcome.isResume })
}

async function slackInteractivityHandler(ctx: RouteCtx): Promise<void> {
    const { req, res, deps } = ctx
    // Signature already verified by the slack_signing guard.
    const rawPayload = (req.body as { payload?: string } | undefined)?.payload
    if (typeof rawPayload !== 'string') {
        res.status(400).json({ error: 'missing_payload' })
        return
    }
    let payload: SlackInteractivityPayload
    try {
        payload = JSON.parse(rawPayload) as SlackInteractivityPayload
    } catch {
        res.status(400).json({ error: 'invalid_payload' })
        return
    }
    const action = payload.actions?.[0]
    if (!action) {
        res.status(400).json({ error: 'no_action' })
        return
    }
    // Tool-approval buttons (`principal`-type approvals) and elevation-grant
    // buttons share this one interactivity endpoint; dispatch on the value tag.
    const approvalAction = decodeApprovalActionValue(action.value)
    if (approvalAction) {
        await handleApprovalDecisionAction(ctx, payload, approvalAction)
        return
    }
    const decoded = decodeElevationActionValue(action.value)
    if (!decoded) {
        res.status(400).json({ error: 'no_elevation_action' })
        return
    }
    const { sessionId, requestId, decision } = decoded
    // The sessionId is decoded from the (attacker-influenceable) Slack action
    // value — scope it to the resolved agent so an elevation decision can't be
    // applied to another agent's session. Mismatch reads as not-found.
    const session = await getOwnedSession(ctx, sessionId)
    if (!session) {
        res.status(404).json({ error: 'session_not_found' })
        return
    }
    const workspaceId = payload.team?.id ?? payload.user?.team_id ?? 'unknown'
    const clickerId = payload.user?.id ?? ''
    const clickerPrincipal: SessionPrincipal = {
        kind: 'slack',
        workspace_id: workspaceId,
        slack_user_id: clickerId,
        agent_user_id: await resolveSlackUserId(deps, session.team_id, session.application_id, workspaceId, clickerId),
    }
    // TODO(slack-elevation): the Grant/Decline + error replies below send their
    // feedback in the synchronous res.json body, which Slack IGNORES for Block
    // Kit `block_actions` — so the message never updates and the "owner only" /
    // "already decided" ephemerals never render. Same bug already fixed for the
    // approval buttons: ack with a bare 200, then POST feedback to
    // `payload.response_url` via `respondViaResponseUrl` (see
    // handleApprovalDecisionAction). Left as a follow-up — separate feature.
    const authz = authorizeGrant(session, requestId, clickerPrincipal)
    if (!authz.ok) {
        if (authz.reason === 'not_session_owner') {
            // Slack's interactivity contract: 200 + an ephemeral message shows
            // only to the clicking user without polluting the thread.
            res.json({
                response_type: 'ephemeral',
                replace_original: false,
                text: 'Only the session owner can decide this elevation request.',
            })
            return
        }
        if (authz.reason === 'request_not_pending') {
            res.json({
                response_type: 'ephemeral',
                replace_original: false,
                text: 'This elevation request has already been decided.',
            })
            return
        }
        res.status(404).json({ error: authz.reason })
        return
    }
    if (decision === 'grant') {
        const result = await applyElevationGrant(deps.queue, session, { requestId, granter: clickerPrincipal })
        res.json({
            response_type: 'in_channel',
            replace_original: true,
            text: `✓ Access granted to ${result.request.requester_display}.`,
        })
        return
    }
    if (decision === 'decline') {
        const declined = await applyElevationDecline(deps.queue, session, { requestId, decider: clickerPrincipal })
        res.json({
            response_type: 'in_channel',
            replace_original: true,
            text: `✗ Request from ${declined.requester_display} declined.`,
        })
        return
    }
    res.status(400).json({ error: 'unknown_decision' })
}

/**
 * Update the source message of a Slack interaction. For Block Kit
 * `block_actions`, Slack ignores the synchronous HTTP body and uses an empty
 * 200 purely as an ack — message replacement / ephemerals MUST be POSTed to the
 * per-interaction `response_url`. Best-effort: the decision already committed
 * server-side, so a Slack hiccup here must never surface as a failure.
 */
async function respondViaResponseUrl(
    deps: TriggerDeps,
    responseUrl: string | undefined,
    message: { response_type?: 'ephemeral' | 'in_channel'; replace_original?: boolean; text: string }
): Promise<void> {
    if (!responseUrl || !deps.http) {
        return
    }
    try {
        await deps.http.fetch(responseUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json; charset=utf-8' },
            body: JSON.stringify(message),
        })
    } catch (err) {
        log.warn({ err: err instanceof Error ? err.message : String(err) }, 'slack_approval_response_url_failed')
    }
}

/**
 * Decide a `principal`-type tool approval from a Slack button click. The
 * authority is a generic identity match — only the session's own principal may
 * decide (the clicking Slack user must be the session owner), which is NOT a
 * PostHog-authority check.
 *
 * The approval row is fetched scoped to the RESOLVED agent and the session is
 * derived FROM the row (`row.session_id`), never from the attacker-influenceable
 * action-value `sessionId` — so the principal-match is always against the
 * approval's own session, mirroring the ingress HTTP decide route. `agent`-type
 * rows are owner-decided in the console and refused here.
 *
 * Block Kit interactions can't be answered in the synchronous body, so we ack
 * with a bare 200 and post all user feedback (the decided-state replacement, or
 * the not-yours / already-decided ephemeral) to the interaction's `response_url`.
 * Exported for unit testing.
 */
export async function handleApprovalDecisionAction(
    ctx: RouteCtx,
    payload: SlackInteractivityPayload,
    decoded: { sessionId: string; requestId: string; decision: 'approve' | 'reject' }
): Promise<void> {
    const { res, deps } = ctx
    if (!deps.approvals) {
        res.status(500).json({ error: 'approvals_not_wired' })
        return
    }
    const { requestId, decision } = decoded
    const notFound = (): Promise<void> =>
        respondViaResponseUrl(deps, payload.response_url, {
            response_type: 'ephemeral',
            replace_original: false,
            text: 'This approval request could not be found.',
        })

    // Fetch the row scoped to the resolved agent, then derive the session from
    // the row — the action-value `sessionId` is attacker-influenceable, so it's
    // never trusted to choose whose principal must match. `agent`-type rows are
    // console-only; collapse them (and a missing row) to a not-found ephemeral.
    const row = await deps.approvals.getForApplication(requestId, ctx.resolved.application.id)
    if (!row || effectiveApprovalType(row.approver_scope) === 'agent') {
        res.json({ ok: true })
        await notFound()
        return
    }
    const session = await getOwnedSession(ctx, row.session_id)
    if (!session) {
        res.json({ ok: true })
        await notFound()
        return
    }
    const workspaceId = payload.team?.id ?? payload.user?.team_id ?? 'unknown'
    const clickerId = payload.user?.id ?? ''
    const clicker: SessionPrincipal = {
        kind: 'slack',
        workspace_id: workspaceId,
        slack_user_id: clickerId,
        agent_user_id: await resolveSlackUserId(deps, session.team_id, session.application_id, workspaceId, clickerId),
    }
    // Principal-match: only the person who drove this session may decide their
    // own gated call. Anyone else (even another workspace participant) is refused
    // with an ephemeral note that doesn't pollute the thread or touch the buttons.
    if (!principalsMatch(session.principal, clicker)) {
        res.json({ ok: true })
        await respondViaResponseUrl(deps, payload.response_url, {
            response_type: 'ephemeral',
            replace_original: false,
            text: 'Only the person who started this session can decide this approval.',
        })
        return
    }
    const result = await applyApprovalDecision(
        { approvals: deps.approvals, queue: deps.queue },
        {
            requestId,
            applicationId: row.application_id,
            decision,
            decidedBy: clicker.agent_user_id ?? clicker.slack_user_id,
        }
    )
    res.json({ ok: true })
    if (!result.ok) {
        await respondViaResponseUrl(deps, payload.response_url, {
            response_type: 'ephemeral',
            replace_original: false,
            text:
                result.error === 'not_queued'
                    ? 'This request has already been decided.'
                    : 'This approval request could not be found.',
        })
        return
    }
    // Replace the buttons with the decided state so they can't be re-clicked and
    // the thread shows the outcome.
    await respondViaResponseUrl(deps, payload.response_url, {
        response_type: 'in_channel',
        replace_original: true,
        text: decision === 'approve' ? '✓ Approved.' : '✗ Rejected.',
    })
}

/**
 * Parse the opaque `value` Slack carries from the elevation message back to
 * the interactivity payload. We pack `(sessionId, requestId, decision)` into
 * one string so the button definition stays self-contained.
 */
export function encodeElevationActionValue(opts: {
    sessionId: string
    requestId: string
    decision: 'grant' | 'decline'
}): string {
    return `elevation:${opts.decision}:${opts.sessionId}:${opts.requestId}`
}

export function decodeElevationActionValue(
    value: string | undefined
): { sessionId: string; requestId: string; decision: 'grant' | 'decline' } | null {
    if (!value) {
        return null
    }
    const parts = value.split(':')
    if (parts.length !== 4 || parts[0] !== 'elevation') {
        return null
    }
    const decision = parts[1]
    if (decision !== 'grant' && decision !== 'decline') {
        return null
    }
    return { decision, sessionId: parts[2], requestId: parts[3] }
}

interface SlackInteractivityPayload {
    type?: string
    team?: { id?: string }
    user?: { id?: string; team_id?: string }
    actions?: Array<{ action_id?: string; value?: string }>
    // Per-interaction webhook for updating the source message. For Block Kit
    // `block_actions`, Slack IGNORES the synchronous HTTP body — message
    // replacement / ephemerals must be POSTed here (or via chat.update).
    response_url?: string
}

/**
 * Fire-and-forget `reactions.add` for the immediate-ack flow. Called from the
 * events handler when `slack.config.ack_reaction` is set; the surrounding
 * `void ... .catch(...)` collapses every error path to a silent no-op so the
 * session enqueue is never blocked.
 */
async function postAckReaction(
    deps: TriggerDeps,
    application: AgentApplication,
    revision: AgentRevision,
    opts: { channel: string; ts: string; name: string }
): Promise<void> {
    const token = await deps.signingSecretResolver.resolve(SLACK_BOT_TOKEN_KEY, revision)
    if (!token) {
        log.warn({ slug: application.slug, reaction: opts.name }, 'ack_reaction_no_bot_token')
        return
    }
    if (!deps.http) {
        log.warn({ slug: application.slug, reaction: opts.name }, 'ack_reaction_no_http_client')
        return
    }
    log.debug(
        { slug: application.slug, channel: opts.channel, ts: opts.ts, reaction: opts.name },
        'ack_reaction_posting'
    )
    const res = await deps.http.fetch('https://slack.com/api/reactions.add', {
        method: 'POST',
        headers: {
            Authorization: `Bearer ${token}`,
            'Content-Type': 'application/json; charset=utf-8',
        },
        body: JSON.stringify({ channel: opts.channel, timestamp: opts.ts, name: opts.name }),
    })
    // Slack returns 200 + `{ ok: false, error: ... }` for application-level
    // failures (`channel_not_found`, `already_reacted`, etc.) — distinct from
    // HTTP transport failures. `already_reacted` is a normal Slack-retry
    // outcome; everything else is a warning. All swallowed (outer .catch guards).
    let body: { ok?: boolean; error?: string } = {}
    try {
        body = (await res.json()) as { ok?: boolean; error?: string }
    } catch {
        // Non-JSON response — Slack hiccup / network proxy. Treat as failure.
    }
    if (!res.ok || body.ok === false) {
        const isAlreadyReacted = body.error === 'already_reacted'
        const fields = {
            slug: application.slug,
            channel: opts.channel,
            ts: opts.ts,
            reaction: opts.name,
            status: res.status,
            slack_error: body.error ?? null,
        }
        if (isAlreadyReacted) {
            log.debug(fields, 'ack_reaction_already_reacted')
        } else {
            log.warn(fields, 'ack_reaction_failed')
        }
        return
    }
    log.info({ slug: application.slug, channel: opts.channel, ts: opts.ts, reaction: opts.name }, 'ack_reaction_ok')
}

/**
 * Post a plain text reply into a thread using the agent's bot token. Used to
 * tell a rejected non-owner (owner-only threads) why their message did
 * nothing. Errors are swallowed (a missing token / unwired http / slack.com
 * hiccup must not break the event ack). Returns true if the message posted.
 */
async function postThreadMessage(
    deps: TriggerDeps,
    application: AgentApplication,
    revision: AgentRevision,
    opts: { channel: string; thread_ts: string; text: string }
): Promise<boolean> {
    const token = await deps.signingSecretResolver.resolve(SLACK_BOT_TOKEN_KEY, revision)
    if (!token || !deps.http) {
        log.warn(
            { slug: application.slug, has_token: Boolean(token), has_http: Boolean(deps.http) },
            'thread_message_skipped'
        )
        return false
    }
    try {
        const res = await deps.http.fetch('https://slack.com/api/chat.postMessage', {
            method: 'POST',
            headers: {
                Authorization: `Bearer ${token}`,
                'Content-Type': 'application/json; charset=utf-8',
            },
            body: JSON.stringify({ channel: opts.channel, thread_ts: opts.thread_ts, text: opts.text }),
        })
        let body: { ok?: boolean; error?: string } = {}
        try {
            body = (await res.json()) as { ok?: boolean; error?: string }
        } catch {
            // Non-JSON response — treat as failure but don't throw.
        }
        if (!res.ok || body.ok === false) {
            log.warn(
                { slug: application.slug, channel: opts.channel, status: res.status, slack_error: body.error ?? null },
                'thread_message_failed'
            )
            return false
        }
        return true
    } catch (err) {
        log.warn(
            { slug: application.slug, channel: opts.channel, err: err instanceof Error ? err.message : String(err) },
            'thread_message_threw'
        )
        return false
    }
}

/**
 * Resolve a clicking Slack user to the same AgentUser id the events trigger
 * would produce. When the identity store is wired this is a stable lookup;
 * without it we fall back to the raw `workspace:user` tuple which matches what
 * the events trigger persists.
 */
async function resolveSlackUserId(
    deps: TriggerDeps,
    teamId: number,
    applicationId: string,
    workspaceId: string,
    userId: string
): Promise<string> {
    const principalId = `${workspaceId}:${userId}`
    if (!deps.identities) {
        return principalId
    }
    const agentUser = await deps.identities.findOrCreate({
        team_id: teamId,
        application_id: applicationId,
        principal_kind: 'slack',
        principal_id: principalId,
        metadata: { workspace: workspaceId, slack_user: userId },
    })
    return agentUser.id
}

interface SlackEvent {
    type: string
    channel: string
    /** `"im"` for a 1:1 DM, `"mpim"` for a group DM, `"channel"`/`"group"`
     *  otherwise. Present on `message` events; absent on `app_mention`. */
    channel_type?: string
    user: string
    team?: string
    text?: string
    ts: string
    thread_ts?: string
    bot_id?: string
}

/** Published `bodySchema` covers only the two envelope shapes we route on
 *  (`url_verification`, `event_callback`). The runtime handler is permissive —
 *  Slack sends a long tail of event types we accept-and-no-op, so we
 *  deliberately don't safeParse against the published schema. */
export const slackTrigger: TriggerModule = {
    type: 'slack',
    routes: [
        {
            method: 'POST',
            path: '/slack/events',
            bodySchema: z.toJSONSchema(SlackEventBodySchema),
            auth: 'slack_signing',
            handler: slackEventsHandler,
        },
        {
            method: 'POST',
            path: '/slack/interactivity',
            // Slack posts urlencoded `payload=<json>` — published schema is the
            // decoded JSON so authoring tools see the actual interactivity
            // contract, not just an opaque form-data envelope.
            bodySchema: z.toJSONSchema(z.object({ payload: z.string() })),
            auth: 'slack_signing',
            handler: slackInteractivityHandler,
        },
    ],
}
