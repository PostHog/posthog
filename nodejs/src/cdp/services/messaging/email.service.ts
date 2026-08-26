import { MessageHeader, SESv2Client, SendEmailCommand, SendEmailCommandInput } from '@aws-sdk/client-sesv2'
import { DateTime } from 'luxon'
import { SendMailOptions } from 'nodemailer'
import { Counter } from 'prom-client'

import { CyclotronInvocationQueueParametersEmailType } from '~/cdp/schema/cyclotron'
import { HogFlowEmailSendingRateLimit, HogFlowEmailSendingRateLimitSchema } from '~/cdp/schema/hogflow'
import {
    CyclotronJobInvocationHogFlow,
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
    HogFunctionType,
    IntegrationType,
    MessageAssetRow,
} from '~/cdp/types'
import { createAddLogFunction, logEntry } from '~/cdp/utils'
import { createInvocationResult } from '~/cdp/utils/invocation-utils'
import { logger } from '~/common/utils/logger'

import { IntegrationManagerService } from '../managers/integration-manager.service'
import { RecipientManagerRecipient, RecipientsManagerService } from '../managers/recipients-manager.service'
import { TeamWorkflowsConfigService } from '../managers/team-workflows-config.service'
import { RateLimiterService } from '../rate-limiter/rate-limiter.service'
import { selectEmailSenderIntegrationId } from './email-sender-selection'
import { EmailSuppressionService } from './email-suppression.service'
import { addTrackingToEmail, resolveEmailEngagementDistinctId } from './email-tracking.service'
import { mailDevTransport, mailDevWebUrl } from './helpers/maildev'
import { maybeAddPreheaderToEmail } from './helpers/preheader'
import { EmailTrackingCodeSigner, TRACKING_CODE_HEADER_NAME } from './helpers/tracking-code'
import { MessageAssetsService } from './message-assets.service'
import { RecipientTokensService } from './recipient-tokens.service'

const sesThrottleResponsesTotal = new Counter({
    name: 'cdp_ses_throttle_responses_total',
    help: 'SES API responses classified as throttle/rate-limit. Sustained nonzero rate means the local bucket is set too high vs. the SES quota.',
    labelNames: ['error_code'],
})

/**
 * SES error codes that signal a transient rate-limit shape — safe to retry
 * shortly after. `TooManyRequestsException` is the SES-v2-specific class;
 * `ThrottlingException` is a generic AWS SDK error code that can surface
 * from the underlying transport layer for the same condition (not exported
 * as a class for sesv2, so we match by `name`).
 *
 * `SendingPausedException` is *not* on this list — it signals a reputation
 * or account-state problem that won't recover in seconds. Retrying within
 * 500ms just burns reschedules; the job hard-fails instead, surfaces via
 * `email_failed`, and the underlying SES config needs operator attention.
 */
const SES_THROTTLE_ERROR_NAMES = ['TooManyRequestsException', 'ThrottlingException'] as const
type SesThrottleErrorName = (typeof SES_THROTTLE_ERROR_NAMES)[number]

function isSesThrottleError(error: unknown): error is Error & { name: SesThrottleErrorName } {
    return error instanceof Error && (SES_THROTTLE_ERROR_NAMES as readonly string[]).includes(error.name)
}

/**
 * Tagged error signalling that SES rejected the send for a transient,
 * rate-limit-shaped reason. The caller schedules a retry instead of failing
 * the job. Carries the SES error name for metrics and the retry delay we
 * pick locally (SES doesn't return a Retry-After header).
 */
export class SESThrottleError extends Error {
    public readonly errorCode: SesThrottleErrorName
    public readonly retryAfterMs: number

    constructor(errorCode: SesThrottleErrorName, retryAfterMs: number, message: string) {
        super(message)
        this.name = 'SESThrottleError'
        this.errorCode = errorCode
        this.retryAfterMs = retryAfterMs
    }
}

function pickThrottleRetryDelayMs(): number {
    // Constant 500–1000ms jitter is plenty: the local Valkey bucket already
    // gates re-dequeue at the configured refill rate, so a quick retry will
    // simply re-claim a token if SES capacity has refreshed. Exponential
    // backoff isn't needed at this layer.
    return 500 + Math.floor(Math.random() * 500)
}

const workflowEmailRateLimitedTotal = new Counter({
    name: 'cdp_workflow_email_rate_limited_total',
    help: 'Email sends delayed by a user-configured per-workflow sending rate limit.',
})

// The metadata blob is the flow action's config plus flow-level keys stamped in by
// HogFlowFunctionsService.buildHogFunction; parse defensively since it is untyped.
function parseWorkflowEmailRateLimit(metadata: HogFunctionType['metadata']): HogFlowEmailSendingRateLimit | null {
    const raw = metadata?.email_sending_rate_limit
    if (!raw) {
        return null
    }
    const parsed = HogFlowEmailSendingRateLimitSchema.safeParse(raw)
    return parsed.success ? parsed.data : null
}

function pickWorkflowRateLimitRetryDelayMs(refillPerSecond: number): number {
    // Wake around when the next token accrues. The 1x-2x jitter spreads a queued backlog's
    // retries so they don't all re-dequeue (and re-claim against one token) at the same instant.
    // Clamped so second-scale limits don't churn the queue and hour-scale limits still wake
    // often enough to drain promptly once capacity frees up.
    const tokenIntervalMs = 1000 / refillPerSecond
    const baseMs = Math.min(Math.max(tokenIntervalMs, 1_000), 5 * 60 * 1_000)
    return Math.floor(baseMs * (1 + Math.random()))
}

export interface EmailServiceConfig {
    sesAccessKeyId: string
    sesSecretAccessKey: string
    sesRegion: string
    sesEndpoint: string
    // Configuration set with ESP-level open/click tracking enabled.
    sesTrackedConfigurationSet: string
    // Configuration set without open/click tracking. Empty means not provisioned: tracking-off
    // sends fall back to the tracked set (with a warning) rather than failing.
    sesUntrackedConfigurationSet: string
    // When true, sends carry TenantName so SES attributes reputation per team. Requires every
    // sending identity to have a tenant resource association — see EMAIL_SES_TENANT_ATTRIBUTION_ENABLED.
    sesTenantAttributionEnabled: boolean
}

/**
 * Strips control characters from an email subject to prevent header injection
 * and delivery issues. Removes ASCII 0-31 (except horizontal tab) and DEL (127).
 */
export function sanitizeEmailSubject(subject: string): string {
    return subject
        .replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, '')
        .replace(/[\r\n]+/g, ' ')
        .trim()
}

// Splits a comma-separated address list and extracts the bare email from any RFC-822
// `"Name" <email@x>` entries. Used by the pre-send suppression check to normalize cc/bcc entries
// before matching against the suppression list (which stores bare, lower-cased addresses).
export function extractEmailsFromAddressList(value: string | undefined): string[] {
    if (typeof value !== 'string' || value.trim().length === 0) {
        return []
    }
    return value
        .split(',')
        .map((raw) => {
            const trimmed = raw.trim()
            const bracketed = trimmed.match(/<([^>]+)>/)
            return (bracketed ? bracketed[1] : trimmed).trim()
        })
        .filter((addr) => addr.length > 0)
}

// Deliberately stricter than RFC 5322: exactly one @, a dotted domain, and none of the
// characters that would let a templated value smuggle a second address or break out of the
// RFC-822 `"Name" <email>` framing (whitespace, quotes, angle brackets, list separators).
const FROM_OVERRIDE_EMAIL_REGEX = /^[^\s@"<>,;]+@[^\s@"<>,;]+\.[^\s@"<>,;]+$/

// The display name is embedded as `"${name}" <email>`, so strip the characters that would
// terminate the quoted phrase or start the address part, plus control characters.
function sanitizeFromName(name: string): string {
    return name.replace(/[\x00-\x1F\x7F"<>\\]/g, '').trim()
}

export function parseAddressList(value?: string): string[] | undefined {
    if (!value || !value.trim()) {
        return undefined
    }
    const result = value
        .split(',')
        .map((addr) => addr.trim())
        .filter((addr) => addr.length > 0)
    return result.length > 0 ? result : undefined
}

export class EmailService {
    sesV2Client: SESv2Client | null

    private recipientTokensService: RecipientTokensService
    private untrackedConfigSetWarningLogged = false

    constructor(
        private sesConfig: EmailServiceConfig,
        private integrationManager: IntegrationManagerService,
        private teamWorkflowsConfigService: TeamWorkflowsConfigService,
        encryptionSaltKeys: string,
        siteUrl: string,
        private trackingCodeSigner: EmailTrackingCodeSigner,
        private emailSuppressionService: EmailSuppressionService,
        private recipientsManager: RecipientsManagerService,
        private messageAssetsService?: MessageAssetsService,
        private workflowEmailRateLimiter: RateLimiterService | null = null
    ) {
        this.sesV2Client = this.sesConfig.sesRegion
            ? new SESv2Client({
                  region: this.sesConfig.sesRegion,
                  endpoint: this.sesConfig.sesEndpoint || undefined,
              })
            : null
        this.recipientTokensService = new RecipientTokensService(encryptionSaltKeys, siteUrl)
    }

    // Send email. `isTest` flags sends from the editor's "Run test" path so the tracking code
    // embedded in the email tells the SES webhook to skip recording metrics for test traffic.
    public async executeSendEmail(
        invocation: CyclotronJobInvocationHogFunction,
        isTest = false
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>> {
        if (invocation.queueParameters?.type !== 'email') {
            throw new Error('Invocation passed to sendEmail is not an email function')
        }

        const result = createInvocationResult<CyclotronJobInvocationHogFunction>(
            invocation,
            // Preserve the incoming priority: createInvocationResult otherwise resets it to 0, which
            // on a throttle reschedule (below) would rewrite the send's priority class — an entering
            // bulk send (priority 1) would return as fast-lane (0). The queue caller sets this to the
            // send's class before calling in, so carrying it through keeps a throttled retry in class.
            { queuePriority: invocation.queuePriority },
            {
                finished: true,
            }
        )
        const addLog = createAddLogFunction(result.logs)

        const params = invocation.queueParameters
        const integrationId = selectEmailSenderIntegrationId(invocation.id, params.from)
        const integration = await this.integrationManager.get(integrationId)

        let success: boolean = false
        let throttled: boolean = false
        let assetRow: MessageAssetRow | null = null
        let trackingEnabled = true

        try {
            // Team-level kill switch: staff suspend all workflow email for a team whose sender
            // reputation endangers shared SES deliverability. Same choke-point placement as the
            // suppression check below so no upstream route can bypass it. Test sends are blocked
            // too — they hit SES and count against the tenant all the same.
            if (await this.teamWorkflowsConfigService.isEmailSendingSuspended(invocation.teamId)) {
                addLog('warn', 'Skipping send: email sending is suspended for this project')
                if (!isTest) {
                    result.metrics.push({
                        team_id: invocation.teamId,
                        app_source_id: invocation.parentRunId ?? invocation.functionId,
                        instance_id: invocation.state.actionId || invocation.id,
                        metric_kind: 'email',
                        metric_name: 'email_suspended',
                        count: 1,
                    })
                }
                result.invocation.state.vmState?.stack.push({ success: false })
                return result
            }

            // Wrong-team references deliberately read as not-found so an ID's existence on another team can't be probed
            if (!integration || integration.team_id !== invocation.teamId) {
                throw new Error(
                    "Email integration not found. The sender configured for this step no longer exists — select a new sender in the workflow's email step."
                )
            }
            if (integration.kind !== 'email') {
                throw new Error(
                    "The integration configured for this step is not an email channel — select an email sender in the workflow's email step."
                )
            }

            const from = this.resolveFromSender(integration, params.from, addLog)

            // Single choke point for the suppression check — every send path lands here regardless
            // of whether the invocation came from a workflow action or an email destination hog
            // function. Checking here means callers can't bypass it by taking a different upstream
            // route. Covers `to`, `cc`, and `bcc`; a suppressed address anywhere blocks the send.
            const skipReason = await this.buildSuppressionSkipReason(invocation.teamId, params)
            if (skipReason) {
                addLog('info', skipReason)
                if (!isTest) {
                    result.metrics.push({
                        team_id: invocation.teamId,
                        app_source_id: invocation.parentRunId ?? invocation.functionId,
                        instance_id: invocation.state.actionId || invocation.id,
                        metric_kind: 'email',
                        metric_name: 'email_suppressed',
                        count: 1,
                    })
                }
                result.invocation.state.vmState?.stack.push({ success: false })
                return result
            }

            // Like suppression, the tracking decision lives at this choke point so every send path
            // (workflow action or email destination hog function) resolves it the same way.
            trackingEnabled = await this.resolveTrackingEnabled(result.invocation, params)

            // User-configured per-workflow pacing. Claimed last, after every skip gate, so a
            // suspended or suppressed send never spends a token. Test sends bypass it. When the
            // limiter's Valkey is down claimUpTo returns 0, so sends wait (never drop) until it
            // recovers — same fail-closed stance as the global SES gate.
            const workflowRateLimit = parseWorkflowEmailRateLimit(invocation.hogFunction.metadata)
            if (workflowRateLimit && this.workflowEmailRateLimiter && !isTest) {
                const periodSeconds = workflowRateLimit.period === 'minute' ? 60 : 3600
                const refillPerSecond = workflowRateLimit.count / periodSeconds
                // Burst capacity is about one second of budget, not the full count: a bucket that
                // could hold `count` starts full and refills within the same period, so a fresh (or
                // idle-expired) bucket would send ~2x the configured limit in its first period.
                // A near-empty bucket keeps every window at ~count and spreads sends evenly, which
                // is what the pacing is for.
                const capacity = Math.max(1, Math.ceil(refillPerSecond))
                const granted = await this.workflowEmailRateLimiter.claimUpTo({
                    key: `@posthog/workflow-email-rate/${invocation.teamId}/${invocation.functionId}`,
                    requested: 1,
                    capacity,
                    refillPerSecond,
                })
                if (granted === 0) {
                    workflowEmailRateLimitedTotal.inc()
                    result.finished = false
                    // Re-attach the email payload before rescheduling. createInvocationResult cleared
                    // queueParameters, so without this the rescheduled dequeue has no 'email' params to
                    // re-enter the send path — the retry would resume the Hog VM instead and drop the
                    // send. Mirrors the fetch-retry (`result.invocation.queueParameters = params`) and
                    // queue-routing paths, which re-attach the same way.
                    result.invocation.queueParameters = params
                    const retryDelayMs = pickWorkflowRateLimitRetryDelayMs(refillPerSecond)
                    result.invocation.queueScheduledAt = DateTime.utc().plus({ milliseconds: retryDelayMs })
                    addLog(
                        'info',
                        `Sending rate limit reached (${workflowRateLimit.count} emails per ${workflowRateLimit.period}); retrying this email in ${Math.round(retryDelayMs / 1000)}s`
                    )
                    return result
                }
            }

            switch (integration.config.provider ?? 'ses') {
                case 'maildev':
                    await this.sendEmailWithMaildev(result, params, from, trackingEnabled, isTest)
                    break
                case 'ses':
                    await this.sendEmailWithSES(result, params, from, trackingEnabled, isTest)
                    break

                case 'unsupported':
                    throw new Error('Email delivery mode not supported')
            }

            // Emit the `[Email:…]` token in the success log only when an asset row
            // will actually be captured; `renderWorkflowLogMessage` renders it as the
            // "View email" chip, so suppressing it for skipped captures keeps the chip
            // from 404-ing on click.
            if (!isTest && this.messageAssetsService) {
                assetRow = this.messageAssetsService.buildRowForEmail(invocation, params)
            }
            const viewEmailToken = assetRow ? ` [Email:${invocation.id}:${invocation.state.actionId ?? ''}]` : ''
            addLog('info', `Email sent to ${params.to.email} from ${from.name} <${from.email}>${viewEmailToken}`)
            success = true
        } catch (error) {
            if (error instanceof SESThrottleError) {
                // Treat as a transient delivery delay — reschedule rather than fail
                // the job. Our local bucket is the primary throttle; this path
                // catches the cases where SES disagrees with our estimate.
                throttled = true
                result.finished = false
                result.invocation.queueScheduledAt = DateTime.utc().plus({ milliseconds: error.retryAfterMs })
                addLog('warn', `SES rate-limited (${error.errorCode}); rescheduling email in ${error.retryAfterMs}ms`)
            } else {
                addLog('error', error.message)
                result.error = error.message
                result.finished = true
            }
        }

        if (throttled) {
            // On throttle, skip both the VM-state push and the business-metric
            // emit. The eventual successful retry will produce `email_sent` and
            // push the success bit to the VM stack — pushing them now would
            // double-count and lie about the send outcome.
            return result
        }

        // Push the response to the VM stack if running inline (not from the email queue)
        result.invocation.state.vmState?.stack.push({
            success,
        })

        // Test sends (from the editor's "Run test") must not record metrics — keep them out of the
        // workflow's Metrics tab, mirroring the isTest skip the SES webhook applies to delivery/open/click.
        if (!isTest) {
            result.metrics.push({
                team_id: invocation.teamId,
                app_source_id: invocation.parentRunId ?? invocation.functionId,
                instance_id: invocation.state.actionId || invocation.id,
                metric_kind: 'email',
                metric_name: success ? 'email_sent' : 'email_failed',
                count: 1,
            })

            // Untracked sends can never produce opens/clicks, so record them separately: open/click
            // rates are computed against (delivered - untracked) to avoid deflation.
            if (success && !trackingEnabled) {
                result.metrics.push({
                    team_id: invocation.teamId,
                    app_source_id: invocation.parentRunId ?? invocation.functionId,
                    instance_id: invocation.state.actionId || invocation.id,
                    metric_kind: 'email',
                    metric_name: 'email_untracked',
                    count: 1,
                })
            }

            if (success && assetRow) {
                result.messageAssets.push(assetRow)
            }
        }

        const distinctId = resolveEmailEngagementDistinctId(invocation)
        if (
            distinctId &&
            !isTest &&
            (await this.teamWorkflowsConfigService.shouldCaptureEngagementEvents(invocation.teamId))
        ) {
            result.capturedPostHogEvents.push({
                team_id: invocation.teamId,
                timestamp: new Date().toISOString(),
                distinct_id: distinctId,
                event: success ? '$workflows_email_sent' : '$workflows_email_failed',
                properties: {
                    $workflow_id: invocation.functionId,
                    $workflow_action_id: invocation.state.actionId,
                    $email_to: params.to.email,
                    $email_subject: params.subject,
                    // Always set, never conditional: an untracked send can never produce a
                    // `$workflows_email_opened` or `$workflows_email_link_clicked`, so without this
                    // dimension on the send there is no way to build an open rate in an insight that
                    // isn't deflated by however much of the audience declined tracking.
                    $email_tracking_enabled: trackingEnabled,
                },
            })
        }

        return result
    }

    // Returns a human-readable log string when any destination address is suppressed for the team,
    // or null when the send should proceed. Scans to + cc + bcc — SES delivers to every list, so a
    // suppressed address anywhere blocks the whole send. `cc` and `bcc` can be comma-separated
    // lists with RFC-822 `"Name" <email>` entries; we strip the angle-bracketed address before
    // matching against the normalized suppression identifier.
    private async buildSuppressionSkipReason(
        teamId: number,
        params: CyclotronInvocationQueueParametersEmailType
    ): Promise<string | null> {
        const recipients: string[] = []
        if (params.to?.email && params.to.email.trim()) {
            recipients.push(params.to.email.trim())
        }
        recipients.push(...extractEmailsFromAddressList(params.cc))
        recipients.push(...extractEmailsFromAddressList(params.bcc))
        if (recipients.length === 0) {
            return null
        }

        const results = await Promise.all(
            recipients.map(async (email) => ({
                email,
                suppressed: await this.emailSuppressionService.isSuppressed(teamId, email),
            }))
        )
        const suppressed = results.filter((r) => r.suppressed).map((r) => r.email)
        if (suppressed.length === 0) {
            return null
        }
        return `Skipping send: recipient(s) on the suppression list — ${suppressed.join(', ')}`
    }

    // Per-send tracking decision, combining two independent controls:
    // 1. Message-level: `tracking_enabled` on the email step's config (via `hogFunction.metadata`,
    //    same as `message_category_type`). False is a hard off regardless of consent. Absent means
    //    tracked, so email destination hog functions (which have no such config) keep tracking.
    // 2. Recipient-level consent (marketing only; transactional exempt per CNIL): the team's
    //    consent mode combined with the recipient's stored $email_tracking preference.
    // Consent lookup failures resolve to untracked (fail closed): tracking without verifiable
    // consent is a compliance risk, while an untracked send only costs metrics.
    private async resolveTrackingEnabled(
        invocation: CyclotronJobInvocationHogFunction,
        params: CyclotronInvocationQueueParametersEmailType
    ): Promise<boolean> {
        if (invocation.hogFunction?.metadata?.tracking_enabled === false) {
            return false
        }
        if (invocation.hogFunction?.metadata?.message_category_type === 'transactional') {
            return true
        }

        try {
            const consentMode = await this.teamWorkflowsConfigService.getEmailTrackingConsentMode(invocation.teamId)
            if (consentMode === 'off') {
                return true
            }

            // The pixel and rewritten links are whole-message artifacts delivered to every list,
            // so consent must hold for every recipient (same reasoning as the suppression check).
            const recipients: string[] = []
            if (params.to?.email && params.to.email.trim()) {
                recipients.push(params.to.email.trim())
            }
            recipients.push(...extractEmailsFromAddressList(params.cc))
            recipients.push(...extractEmailsFromAddressList(params.bcc))

            const consents = await Promise.all(
                recipients.map(async (email) => {
                    const recipient = await this.recipientsManager.get({
                        teamId: invocation.teamId,
                        identifier: email,
                    })
                    return recipient ? this.recipientsManager.getEmailTrackingPreference(recipient) : 'NO_PREFERENCE'
                })
            )
            return consents.every((consent) =>
                consentMode === 'opt_in' ? consent === 'OPTED_IN' : consent !== 'OPTED_OUT'
            )
        } catch (error) {
            logger.warn('Email tracking consent lookup failed - sending untracked', {
                teamId: invocation.teamId,
                functionId: invocation.functionId,
                error: error instanceof Error ? error.message : String(error),
            })
            return false
        }
    }

    // The tracked and untracked configuration sets share the same delivery/bounce/complaint event
    // destination (suppression and the Metrics tab depend on those events); they differ only in
    // ESP-level open/click tracking.
    private resolveConfigurationSetName(
        trackingEnabled: boolean,
        invocation: CyclotronJobInvocationHogFunction
    ): string {
        if (trackingEnabled) {
            return this.sesConfig.sesTrackedConfigurationSet
        }
        if (this.sesConfig.sesUntrackedConfigurationSet) {
            return this.sesConfig.sesUntrackedConfigurationSet
        }
        // The missing set is static per process - one warning is signal, one per send is noise.
        if (!this.untrackedConfigSetWarningLogged) {
            this.untrackedConfigSetWarningLogged = true
            logger.warn(
                'Email tracking disabled for send but no untracked SES configuration set is configured - falling back to the tracked set, ESP-level open/click tracking may still apply',
                { teamId: invocation.teamId, functionId: invocation.functionId }
            )
        }
        return this.sesConfig.sesTrackedConfigurationSet
    }

    private resolveFromSender(
        integration: IntegrationType,
        from: CyclotronInvocationQueueParametersEmailType['from'],
        addLog: ReturnType<typeof createAddLogFunction>
    ): { email: string; name: string } {
        if (!integration.config.verified) {
            throw new Error('The selected email integration domain is not verified')
        }

        if (!integration.config.email || !integration.config.name) {
            throw new Error('The selected email integration is not configured correctly')
        }

        // Overrides arrive already rendered by the templating engine, so a template that
        // resolved to nothing means "no override" and the integration's stored sender applies.
        const overrideName = from.name ? sanitizeFromName(from.name) : ''

        return {
            email: this.resolveFromEmailAddress(integration, from.email?.trim(), addLog),
            name: overrideName || integration.config.name,
        }
    }

    // An unusable override degrades to the integration's own sender rather than failing the send.
    // Steps authored before mid-2026 carry a placeholder address written by an old sender picker,
    // so throwing here fails sends whose author never typed an address at all.
    private resolveFromEmailAddress(
        integration: IntegrationType,
        overrideEmail: string | undefined,
        addLog: ReturnType<typeof createAddLogFunction>
    ): string {
        if (!overrideEmail) {
            return integration.config.email
        }

        if (!FROM_OVERRIDE_EMAIL_REGEX.test(overrideEmail)) {
            addLog(
                'warn',
                `Ignoring the custom sender address "${overrideEmail}": it is not a valid email address. Sending from ${integration.config.email} instead. Fix the From address in the workflow's email step so it resolves to a single valid address.`
            )
            return integration.config.email
        }

        // Verification is domain-level (the DNS records cover the whole domain), so any address
        // on the integration's domain is exactly as verified as the integration's own address.
        // Anything off-domain is discarded: honoring it would let a workflow send as a domain the
        // team never proved ownership of.
        const integrationDomain: string = (
            integration.config.domain ??
            integration.config.email.split('@')[1] ??
            ''
        ).toLowerCase()
        const overrideDomain = overrideEmail.split('@')[1].toLowerCase()
        if (!integrationDomain || overrideDomain !== integrationDomain) {
            addLog(
                'warn',
                `Ignoring the custom sender address "${overrideEmail}": it is not on the verified domain "${integrationDomain}" of the selected sender. Sending from ${integration.config.email} instead. Use an address on that domain, or select a different sender in the workflow's email step.`
            )
            return integration.config.email
        }

        return overrideEmail
    }

    // Send email to local maildev instance for testing (DEBUG=1 only)
    private async sendEmailWithMaildev(
        result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>,
        params: CyclotronInvocationQueueParametersEmailType,
        from: { email: string; name: string },
        trackingEnabled: boolean,
        isTest = false
    ): Promise<void> {
        // This can timeout but there is no native timeout so we do our own one
        const mailOptions: SendMailOptions = {
            from: from.name ? `"${from.name}" <${from.email}>` : from.email,
            to: params.to.name ? `"${params.to.name}" <${params.to.email}>` : params.to.email,
            subject: sanitizeEmailSubject(params.subject),
            text: params.text,
            ...(params.html
                ? {
                      html: trackingEnabled
                          ? addTrackingToEmail(params.html, result.invocation, this.trackingCodeSigner, isTest)
                          : params.html,
                  }
                : {}),
        }

        const ccAddresses = parseAddressList(params.cc)
        const bccAddresses = parseAddressList(params.bcc)

        if (ccAddresses) {
            mailOptions.cc = ccAddresses
        }
        if (bccAddresses) {
            mailOptions.bcc = bccAddresses
        }

        const response = await mailDevTransport!.sendMail(mailOptions)

        if (!response.accepted) {
            throw new Error(`Failed to send email to maildev: ${JSON.stringify(response)}`)
        }

        result.logs.push(logEntry('debug', `Email sent to your local maildev server: ${mailDevWebUrl}`))
    }

    private async sendEmailWithSES(
        result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>,
        params: CyclotronInvocationQueueParametersEmailType,
        from: { email: string; name: string },
        trackingEnabled: boolean,
        isTest = false
    ): Promise<void> {
        if (!this.sesV2Client) {
            throw new Error('SES is not configured - set SES_REGION and AWS credentials')
        }
        const distinctId = resolveEmailEngagementDistinctId(result.invocation)
        // Full signed code (with distinct_id + isTest) rides in the header; the short unsigned
        // carrier (no distinct_id/isTest) goes in the SES EmailTag, guaranteed under the 256-char
        // tag-value limit. The webhook reads the header first and only falls back to the tag.
        // A flow's email runs as a hog function invocation built by spreading the flow invocation, so
        // `hogFlow` is present at runtime even though the type is the narrower hog function shape.
        const workflowVersion =
            'hogFlow' in result.invocation
                ? (result.invocation as unknown as CyclotronJobInvocationHogFlow).hogFlow.version
                : undefined
        const trackingCode = this.trackingCodeSigner.generate(
            { ...result.invocation, distinctId, workflowVersion },
            isTest
        )
        const shortTrackingCode = this.trackingCodeSigner.generateShort(result.invocation)

        const htmlBody = params.html
            ? {
                  Html: {
                      Data: maybeAddPreheaderToEmail(
                          trackingEnabled
                              ? addTrackingToEmail(
                                    params.html,
                                    result.invocation,
                                    this.trackingCodeSigner,
                                    isTest,
                                    'ses'
                                )
                              : params.html,
                          params.preheader
                      ),
                      Charset: 'UTF-8',
                  },
              }
            : {}

        const sendEmailParams: SendEmailCommandInput = {
            FromEmailAddress: from.name ? `"${from.name}" <${from.email}>` : from.email,
            Destination: {
                ToAddresses: [params.to.name ? `"${params.to.name}" <${params.to.email}>` : params.to.email],
            },
            Content: {
                Simple: {
                    Subject: {
                        Data: sanitizeEmailSubject(params.subject),
                        Charset: 'UTF-8',
                    },
                    Body: {
                        Text: {
                            Data: params.text,
                            Charset: 'UTF-8',
                        },
                        ...htmlBody,
                    },
                },
            },
            ConfigurationSetName: this.resolveConfigurationSetName(trackingEnabled, result.invocation),
            // Short unsigned tag kept as a backwards-compat carrier for in-flight messages and
            // environments where the configuration set isn't yet emitting original headers.
            EmailTags: [{ Name: 'ph_id', Value: shortTrackingCode }],
            FeedbackForwardingEmailAddress: from.email,
        }

        if (this.sesConfig.sesTenantAttributionEnabled) {
            // Attributes the send to the team's SES tenant so AWS tracks reputation per team and
            // its reputation policy can pause one tenant instead of the shared account. `team-<id>`
            // is the provisioning convention (products/workflows/backend/providers/ses.py and
            // posthog/management/commands/migrate_ses_tenants.py). Deliberately NOT gated on
            // isTest: test-panel sends are real over-the-wire SES sends, so leaving them
            // unattributed would (a) push their bounces onto the shared account's reputation and
            // (b) let a paused tenant keep sending via "Run test". The isTest skips elsewhere in
            // this class only shield our internal metrics, a separate concern from SES-side
            // attribution; test volume is far below the representative volume AWS needs for a
            // reputation finding.
            sendEmailParams.TenantName = `team-${result.invocation.teamId}`
        }

        // Authoritative tracking-code carrier: a custom MIME header. Header values aren't
        // 256-char-bounded the way SES tag values are, so they safely carry the signed code
        // (with distinct_id). The configuration set's event destination needs
        // `IncludeOriginalHeaders: true` for the webhook to surface this header.
        const trackingHeader: MessageHeader = { Name: TRACKING_CODE_HEADER_NAME, Value: trackingCode }

        const isTransactionalEmail = result.invocation.hogFunction?.metadata?.message_category_type === 'transactional'
        if (sendEmailParams.Content?.Simple) {
            const unsubscribeHeaders = !isTransactionalEmail
                ? this.generateUnsubscribeHeaders({
                      team_id: result.invocation.teamId,
                      identifier: params.to.email,
                  })
                : []
            sendEmailParams.Content.Simple.Headers = [...unsubscribeHeaders, trackingHeader]
        }

        const replyToAddresses = parseAddressList(params.replyTo)
        const ccAddresses = parseAddressList(params.cc)
        const bccAddresses = parseAddressList(params.bcc)

        if (replyToAddresses) {
            sendEmailParams.ReplyToAddresses = replyToAddresses
        }
        if (ccAddresses) {
            sendEmailParams.Destination!.CcAddresses = ccAddresses
        }
        if (bccAddresses) {
            sendEmailParams.Destination!.BccAddresses = bccAddresses
        }

        try {
            const response = await this.sesV2Client.send(new SendEmailCommand(sendEmailParams))
            if (!response.MessageId) {
                throw new Error('No messageId returned from SES')
            }
        } catch (error: unknown) {
            if (isSesThrottleError(error)) {
                sesThrottleResponsesTotal.inc({ error_code: error.name })
                throw new SESThrottleError(error.name, pickThrottleRetryDelayMs(), error.message)
            }
            const message = error instanceof Error ? error.message : String(error)
            throw new Error(`Failed to send email via SES: ${message}`)
        }
    }

    private generateUnsubscribeHeaders(
        recipient: Pick<RecipientManagerRecipient, 'team_id' | 'identifier'>
    ): MessageHeader[] {
        return [
            {
                Name: 'List-Unsubscribe',
                Value: `<${this.recipientTokensService.generateOneClickUnsubscribeUrl(recipient)}>`,
            },
            {
                Name: 'List-Unsubscribe-Post',
                Value: 'List-Unsubscribe=One-Click',
            },
        ]
    }
}
