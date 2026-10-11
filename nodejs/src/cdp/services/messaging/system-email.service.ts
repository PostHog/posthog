import { SESv2Client, SendEmailCommand, SendEmailCommandInput } from '@aws-sdk/client-sesv2'
import { Counter } from 'prom-client'

import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult, MinimalAppMetric } from '~/cdp/types'
import { logEntry } from '~/cdp/utils'
import { buildIntegerMatcher } from '~/common/config/config'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { isDevEnv } from '~/common/utils/env-utils'
import { logger } from '~/common/utils/logger'
import { TeamManager } from '~/common/utils/team-manager'
import { ValueMatcher } from '~/types'

import { TeamWorkflowsConfigService } from '../managers/team-workflows-config.service'
import { RateLimiterService } from '../rate-limiter/rate-limiter.service'
import { AUTO_SUBMITTED_HEADER, sanitizeEmailSubject } from './email.service'
import { mailDevTransport } from './helpers/maildev'
import { createSesV2Client } from './helpers/ses-client'

export const SYSTEM_EMAIL_TEMPLATE_ID = 'template-posthog-email'
export const SYSTEM_EMAIL_MAX_RECIPIENTS = 50
export const SYSTEM_EMAIL_MAX_SUBJECT_LENGTH = 200
export const SYSTEM_EMAIL_MAX_BODY_LENGTH = 4000
export const SYSTEM_EMAIL_SUBJECT_PREFIX = '[PostHog] '
export const SYSTEM_EMAIL_HOURLY_LIMIT = 20
export const SYSTEM_EMAIL_DAILY_LIMIT = 100

const MAX_ACTION_LABEL_LENGTH = 60
const DEFAULT_ACTION_LABEL = 'Open in PostHog'
const SEND_CONCURRENCY = 10

// Longer than the window each bucket paces. An idle bucket that expires comes back full, so a
// shorter TTL would hand a team a fresh allowance before the bucket refilled by itself.
const HOUR_BUCKET_TTL_SECONDS = 6 * 60 * 60
const DAY_BUCKET_TTL_SECONDS = 3 * 24 * 60 * 60

type SystemEmailOutcome =
    | 'sent'
    | 'failed'
    | 'rate_limited'
    | 'skipped_no_recipients'
    | 'not_eligible'
    | 'not_enabled'
    | 'not_configured'
    | 'suspended'
    | 'invalid_arguments'

const systemEmailTotal = new Counter({
    name: 'cdp_system_email_total',
    help: 'Calls to sendSystemEmail by outcome. One call can deliver to several recipients.',
    labelNames: ['outcome'] as const,
})

export type SystemEmailResult = { success: boolean; error?: string }

export type SystemEmailMessage = {
    from: { email: string; name: string }
    replyTo: string
    to: string
    subject: string
    html: string
    text: string
}

export interface SystemEmailTransport {
    send(message: SystemEmailMessage): Promise<void>
}

export interface SystemEmailTransportConfig {
    sesRegion: string
    sesEndpoint: string
    // Configuration set without open or click tracking. Empty means the send names no set.
    sesUntrackedConfigurationSet: string
    sesTenant: string
}

export interface SystemEmailServiceConfig {
    enabledTeams: string
    fromAddress: string
    fromName: string
    replyTo: string
    siteUrl: string
}

export interface SystemEmailServiceDependencies {
    postgres: PostgresRouter
    teamManager: TeamManager
    teamWorkflowsConfigService: TeamWorkflowsConfigService
    rateLimiter: RateLimiterService
    transport: SystemEmailTransport
}

type SystemEmailContent = {
    subject: string
    body: string
    actionUrl: string | null
    actionLabel: string
}

type SystemEmailFooter = {
    projectName: string
    functionName: string
    functionUrl: string | null
    settingsUrl: string | null
}

function formatSender(from: { email: string; name: string }): string {
    const name = from.name.replace(/[\x00-\x1F\x7F"<>\\]/g, '').trim()
    return name ? `"${name}" <${from.email}>` : from.email
}

export class SesSystemEmailTransport implements SystemEmailTransport {
    private client: SESv2Client | null

    constructor(private config: SystemEmailTransportConfig) {
        this.client = createSesV2Client(config)
    }

    async send(message: SystemEmailMessage): Promise<void> {
        if (!this.client) {
            throw new Error('SES is not configured - set SES_REGION and AWS credentials')
        }

        const params: SendEmailCommandInput = {
            FromEmailAddress: formatSender(message.from),
            Destination: { ToAddresses: [message.to] },
            Content: {
                Simple: {
                    Subject: { Data: message.subject, Charset: 'UTF-8' },
                    Body: {
                        Text: { Data: message.text, Charset: 'UTF-8' },
                        Html: { Data: message.html, Charset: 'UTF-8' },
                    },
                    Headers: [AUTO_SUBMITTED_HEADER],
                },
            },
        }
        if (this.config.sesUntrackedConfigurationSet) {
            params.ConfigurationSetName = this.config.sesUntrackedConfigurationSet
        }
        // One tenant for all system email, so these sends never count against the SES reputation
        // of the team's own `team-<id>` tenant, and a paused team tenant does not block them.
        if (this.config.sesTenant) {
            params.TenantName = this.config.sesTenant
        }
        if (message.replyTo) {
            params.ReplyToAddresses = [message.replyTo]
        }

        const response = await this.client.send(new SendEmailCommand(params))
        if (!response.MessageId) {
            throw new Error('No messageId returned from SES')
        }
    }
}

export class MaildevSystemEmailTransport implements SystemEmailTransport {
    async send(message: SystemEmailMessage): Promise<void> {
        const response = await mailDevTransport!.sendMail({
            from: formatSender(message.from),
            to: message.to,
            subject: message.subject,
            text: message.text,
            html: message.html,
            headers: { [AUTO_SUBMITTED_HEADER.Name!]: AUTO_SUBMITTED_HEADER.Value! },
            ...(message.replyTo ? { replyTo: message.replyTo } : {}),
        })
        if (!response.accepted) {
            throw new Error('Failed to send email to maildev')
        }
    }
}

export function createSystemEmailTransport(config: SystemEmailTransportConfig): SystemEmailTransport {
    return isDevEnv() && mailDevTransport ? new MaildevSystemEmailTransport() : new SesSystemEmailTransport(config)
}

export function escapeHtml(value: string): string {
    return value
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;')
}

// Counts code points, so the cut never splits a surrogate pair.
function truncate(value: string, maxLength: number): string {
    const codePoints = Array.from(value)
    return codePoints.length > maxLength ? codePoints.slice(0, maxLength).join('') : value
}

function parseUserIds(value: unknown): number[] {
    if (!Array.isArray(value)) {
        return []
    }
    const ids = value.filter((id): id is number => typeof id === 'number' && Number.isSafeInteger(id) && id > 0)
    return Array.from(new Set(ids)).slice(0, SYSTEM_EMAIL_MAX_RECIPIENTS)
}

export function renderSystemEmail(
    content: SystemEmailContent,
    footer: SystemEmailFooter
): { html: string; text: string } {
    const bodyHtml = escapeHtml(content.body).replace(/\n/g, '<br>')
    const projectName = escapeHtml(footer.projectName)
    const functionName = escapeHtml(footer.functionName)

    const button = content.actionUrl
        ? `<p style="margin:24px 0 0"><a href="${escapeHtml(content.actionUrl)}" style="display:inline-block;padding:8px 16px;border-radius:6px;background:#1d4aff;color:#ffffff;font-weight:600;text-decoration:none">${escapeHtml(content.actionLabel)}</a></p>`
        : ''
    const functionLink = footer.functionUrl ? ` <a href="${escapeHtml(footer.functionUrl)}">View the alert</a>` : ''
    const stopLine = footer.settingsUrl
        ? `To stop these emails, update your <a href="${escapeHtml(footer.settingsUrl)}">notification settings</a>.`
        : 'To stop these emails, update your notification settings.'

    // Every interpolated value below went through `escapeHtml`, or is a URL that `escapeHtml` quotes
    // inside an attribute. The `raw-html-format` rule can't see that, so each interpolated line is
    // suppressed on its own and stays a single line. Escape any value you add here.
    const html = [
        '<!DOCTYPE html>',
        '<html>',
        '<body style="margin:0;padding:24px;background:#ffffff">',
        `<div style="max-width:600px;margin:0 auto;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;color:#1d1f27">`,
        // nosemgrep: javascript.express.security.injection.raw-html-format.raw-html-format
        `<div style="font-size:14px;line-height:1.5">${bodyHtml}</div>`,
        button,
        '<hr style="margin:24px 0;border:none;border-top:1px solid #e5e7eb">',
        '<div style="font-size:12px;line-height:1.5;color:#6b7280">',
        // nosemgrep: javascript.express.security.injection.raw-html-format.raw-html-format
        `Project: ${projectName}<br>`,
        // nosemgrep: javascript.express.security.injection.raw-html-format.raw-html-format
        `Sent by the alert '${functionName}'.${functionLink}<br>`,
        stopLine,
        '</div>',
        '</div>',
        '</body>',
        '</html>',
    ].join('\n')

    const textLines = [content.body]
    if (content.actionUrl) {
        textLines.push('', `${content.actionLabel}: ${content.actionUrl}`)
    }
    textLines.push(
        '',
        '--',
        `Project: ${footer.projectName}`,
        `Sent by the alert '${footer.functionName}'.${footer.functionUrl ? ` View the alert: ${footer.functionUrl}` : ''}`,
        `To stop these emails, update your notification settings${footer.settingsUrl ? `: ${footer.settingsUrl}` : '.'}`
    )

    return { html, text: textLines.join('\n') }
}

/**
 * Sends alert email from a PostHog-owned address to members of the organization that owns the team.
 *
 * The caller's Hog code supplies only the subject, the body and one optional link. The service
 * owns everything else: the recipients come from the triggering event and are checked against the
 * organization, and the sender, the layout and the footer are fixed. That keeps this sender from
 * being used to mail arbitrary addresses or arbitrary HTML from a PostHog domain.
 */
export class SystemEmailService {
    private isTeamEnabled: ValueMatcher<number>
    private siteUrl: string

    constructor(
        private config: SystemEmailServiceConfig,
        private deps: SystemEmailServiceDependencies
    ) {
        this.isTeamEnabled = buildIntegerMatcher(config.enabledTeams, true)
        this.siteUrl = config.siteUrl.replace(/\/+$/, '')
    }

    /**
     * Never throws. A failure of any kind comes back as `success: false`, because this runs inline
     * in the worker and an exception here must not take down the batch.
     */
    public async sendFromInvocation(
        args: unknown,
        result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>
    ): Promise<SystemEmailResult> {
        const invocation = result.invocation
        try {
            return await this.send(args, result)
        } catch (error) {
            // The error name only: SES error messages can carry the recipient address.
            logger.error('[SystemEmail] Unexpected failure', {
                teamId: invocation.teamId,
                functionId: invocation.functionId,
                errorName: error instanceof Error ? error.name : 'unknown',
            })
            return this.finish(result, 'failed', "Couldn't send the email. Try again later.")
        }
    }

    private async send(
        args: unknown,
        result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>
    ): Promise<SystemEmailResult> {
        const invocation = result.invocation
        const hogFunction = invocation.hogFunction

        // A workflow step reuses the template's type and id, and customer events can trigger a
        // workflow. Only the internal events consumer may reach this sender.
        const isWorkflowStep = Boolean(invocation.state.actionId) || 'hogFlow' in invocation
        if (
            hogFunction.type !== 'internal_destination' ||
            hogFunction.template_id !== SYSTEM_EMAIL_TEMPLATE_ID ||
            isWorkflowStep
        ) {
            return this.finish(
                result,
                'not_eligible',
                "This function can't send email. Only an alert created from the 'Email project members' template can."
            )
        }

        if (!this.isTeamEnabled(invocation.teamId)) {
            return this.finish(result, 'not_enabled', "Email alerts aren't available for this project yet.")
        }

        if (!this.config.fromAddress) {
            return this.finish(result, 'not_configured', "Email alerts aren't set up on this PostHog instance.")
        }

        const content = this.parseContent(args, invocation.teamId)
        if (!content) {
            return this.finish(result, 'invalid_arguments', 'The email needs a subject and a body.')
        }

        // Only the staff switch applies. The provider pause is about the team's own SES tenant,
        // and these sends go out under a different tenant.
        const suspension = await this.deps.teamWorkflowsConfigService.getEmailSendingSuspension(invocation.teamId)
        if (suspension === 'staff') {
            return this.finish(
                result,
                'suspended',
                'Email sending is suspended for this project. Contact support to get sending re-enabled.'
            )
        }

        const team = await this.deps.teamManager.getTeam(invocation.teamId)
        const userIds = parseUserIds(invocation.state.globals.event?.properties?.$notify_user_ids)
        const recipients = team && userIds.length ? await this.resolveRecipients(team.organization_id, userIds) : []
        if (!team || recipients.length === 0) {
            return this.finish(result, 'skipped_no_recipients', 'There are no project members to notify.')
        }

        const rateLimitError = await this.claimSendingBudget(invocation.teamId)
        if (rateLimitError) {
            return this.finish(result, 'rate_limited', rateLimitError)
        }

        const { html, text } = renderSystemEmail(content, {
            projectName: sanitizeEmailSubject(team.name ?? ''),
            functionName: sanitizeEmailSubject(hogFunction.name ?? ''),
            functionUrl: this.siteUrl
                ? `${this.siteUrl}/project/${invocation.teamId}/functions/${hogFunction.id}`
                : null,
            settingsUrl: this.siteUrl ? `${this.siteUrl}/settings/user-notifications` : null,
        })

        let failed = 0
        for (let i = 0; i < recipients.length; i += SEND_CONCURRENCY) {
            const outcomes = await Promise.allSettled(
                recipients.slice(i, i + SEND_CONCURRENCY).map((to) =>
                    this.deps.transport.send({
                        from: { email: this.config.fromAddress, name: this.config.fromName },
                        replyTo: this.config.replyTo,
                        to,
                        subject: content.subject,
                        html,
                        text,
                    })
                )
            )
            for (const outcome of outcomes) {
                if (outcome.status === 'rejected') {
                    failed++
                    // The error name only: SES error messages can carry the recipient address.
                    logger.warn('[SystemEmail] Send failed', {
                        teamId: invocation.teamId,
                        functionId: invocation.functionId,
                        errorName: outcome.reason instanceof Error ? outcome.reason.name : 'unknown',
                    })
                }
            }
        }

        const sent = recipients.length - failed
        if (sent > 0) {
            this.pushMetric(result, 'email_sent', sent)
            result.logs.push(logEntry('info', `Email sent to ${sent} project ${sent === 1 ? 'member' : 'members'}.`))
        }
        logger.info('[SystemEmail] Send finished', {
            teamId: invocation.teamId,
            functionId: invocation.functionId,
            sent,
            failed,
        })

        if (failed > 0) {
            return this.finish(
                result,
                'failed',
                `Couldn't send the email to ${failed} of ${recipients.length} project members.`,
                failed
            )
        }

        systemEmailTotal.labels('sent').inc()
        return { success: true }
    }

    private parseContent(args: unknown, teamId: number): SystemEmailContent | null {
        if (!args || typeof args !== 'object' || Array.isArray(args)) {
            return null
        }
        const { subject, body, action_url, action_label } = args as Record<string, unknown>
        if (typeof subject !== 'string' || typeof body !== 'string') {
            return null
        }

        const cleanSubject = truncate(sanitizeEmailSubject(subject), SYSTEM_EMAIL_MAX_SUBJECT_LENGTH)
        const cleanBody = truncate(body.replace(/\r\n?/g, '\n').trim(), SYSTEM_EMAIL_MAX_BODY_LENGTH)
        if (!cleanSubject || !cleanBody) {
            return null
        }

        const label = typeof action_label === 'string' ? sanitizeEmailSubject(action_label) : ''
        return {
            subject: `${SYSTEM_EMAIL_SUBJECT_PREFIX}${cleanSubject}`,
            body: cleanBody,
            actionUrl: this.parseActionUrl(action_url, teamId),
            actionLabel: truncate(label, MAX_ACTION_LABEL_LENGTH) || DEFAULT_ACTION_LABEL,
        }
    }

    private parseActionUrl(value: unknown, teamId: number): string | null {
        if (typeof value !== 'string' || !this.siteUrl) {
            return null
        }
        let normalized: string
        try {
            // Compare the parsed form. A raw prefix check would accept `/project/1/../../login`,
            // which a mail client resolves to a page outside the project.
            normalized = new URL(value.trim()).href
        } catch {
            return null
        }
        return normalized.startsWith(`${this.siteUrl}/project/${teamId}/`) ? normalized : null
    }

    private async resolveRecipients(organizationId: string, userIds: number[]): Promise<string[]> {
        const { rows } = await this.deps.postgres.query<{ email: string }>(
            PostgresUse.COMMON_READ,
            `SELECT posthog_user.email
             FROM posthog_user
             JOIN posthog_organizationmembership ON posthog_user.id = posthog_organizationmembership.user_id
             WHERE posthog_organizationmembership.organization_id = $1
               AND posthog_user.id = ANY($2::int[])
               AND posthog_user.is_active
             ORDER BY posthog_user.id
             LIMIT $3`,
            [organizationId, userIds, SYSTEM_EMAIL_MAX_RECIPIENTS],
            'systemEmailRecipients'
        )
        return rows.map((row) => row.email).filter((email) => typeof email === 'string' && email.length > 0)
    }

    private async claimSendingBudget(teamId: number): Promise<string | null> {
        // The `{teamId}` hash tag keeps both keys in one cluster slot, which the two-key claim needs.
        const claim = await this.deps.rateLimiter.claimAllOrNothingPair(
            [
                {
                    key: `@posthog/system-email/hour/{${teamId}}`,
                    capacity: SYSTEM_EMAIL_HOURLY_LIMIT,
                    refillPerSecond: SYSTEM_EMAIL_HOURLY_LIMIT / 3600,
                    ttlSeconds: HOUR_BUCKET_TTL_SECONDS,
                },
                {
                    key: `@posthog/system-email/day/{${teamId}}`,
                    capacity: SYSTEM_EMAIL_DAILY_LIMIT,
                    refillPerSecond: SYSTEM_EMAIL_DAILY_LIMIT / 86400,
                    ttlSeconds: DAY_BUCKET_TTL_SECONDS,
                },
            ],
            1
        )
        if (claim.granted) {
            return null
        }
        // A null index means the limiter failed. The send still stops, because a send that
        // cannot be counted must not go out.
        if (claim.deniedIndex === null) {
            return "Couldn't check the alert email limit for this project. Try again later."
        }
        const limit =
            claim.deniedIndex === 0 ? `${SYSTEM_EMAIL_HOURLY_LIMIT} per hour` : `${SYSTEM_EMAIL_DAILY_LIMIT} per day`
        return `This project reached its limit of ${limit} for alert emails. Sending resumes when the limit resets.`
    }

    private finish(
        result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>,
        outcome: Exclude<SystemEmailOutcome, 'sent'>,
        error: string,
        count: number = 1
    ): SystemEmailResult {
        systemEmailTotal.labels(outcome).inc()
        const metricName: MinimalAppMetric['metric_name'] =
            outcome === 'rate_limited'
                ? 'email_rate_limited'
                : outcome === 'skipped_no_recipients'
                  ? 'skipped_no_recipients'
                  : 'email_failed'
        this.pushMetric(result, metricName, count)
        logger.info('[SystemEmail] Email not sent', {
            teamId: result.invocation.teamId,
            functionId: result.invocation.functionId,
            outcome,
        })
        return { success: false, error }
    }

    private pushMetric(
        result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>,
        metricName: MinimalAppMetric['metric_name'],
        count: number
    ): void {
        result.metrics.push({
            team_id: result.invocation.teamId,
            app_source_id: result.invocation.functionId,
            instance_id: result.invocation.id,
            metric_kind: 'email',
            metric_name: metricName,
            count,
        })
    }
}
