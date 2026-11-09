import { MessageHeader } from '@aws-sdk/client-sesv2'
import { Counter } from 'prom-client'

import { CyclotronInvocationQueueParametersEmailType } from '~/cdp/schema/cyclotron'
import { RedisV2 } from '~/common/redis/redis-v2'
import { RedisConnectionConfig, RedisPoolConfig } from '~/common/utils/db/redis'
import { logger } from '~/common/utils/logger'
import { captureTeamEvent } from '~/common/utils/posthog'
import { TeamManager } from '~/common/utils/team-manager'

import { escapeHtml } from './helpers/escape-html'
import { maybeAddPreheaderToEmail } from './helpers/preheader'

const BODY_CLOSE_TAG = /<\/body\s*>/gi

export interface SandboxMessage {
    params: CyclotronInvocationQueueParametersEmailType
    headers: MessageHeader[]
}

export interface SandboxEmailSenderConfig {
    enabled: boolean
    tenantName: string
    configurationSetName: string
    fromAddress: string
}

const ROUTE_SETTING_NAMES = {
    tenantName: 'SES_SANDBOX_TENANT_NAME',
    configurationSetName: 'SES_SANDBOX_CONFIGURATION_SET',
    fromAddress: 'SES_SANDBOX_FROM_ADDRESS',
} as const

function emptyRouteSettings(config: SandboxEmailSenderConfig): string[] {
    return (Object.keys(ROUTE_SETTING_NAMES) as (keyof typeof ROUTE_SETTING_NAMES)[])
        .filter((setting) => !config[setting])
        .map((setting) => ROUTE_SETTING_NAMES[setting])
}

export type SandboxEmailBlockReason =
    | 'switch_off'
    | 'not_workflow_step'
    | 'recipient_not_member'
    | 'recipient_unverified'
    | 'check_failed'

const sandboxEmailBlockedTotal = new Counter({
    name: 'cdp_sandbox_email_blocked_total',
    help: 'Sandbox sender sends skipped before delivery, by block reason and by whether the send was a test send.',
    labelNames: ['reason', 'is_test'],
})

const BLOCKED_EVENT_WINDOW_SECONDS = 3600
const EVENT_CAPTURE_TIMEOUT_MS = 1000
export const MAX_OPEN_STORE_CALLS = 10

function appendHtmlFooter(html: string, footer: string): string {
    const footerHtml = `<div>${escapeHtml(footer)}</div>`
    const bodyClose = [...html.matchAll(BODY_CLOSE_TAG)].at(-1)
    if (!bodyClose) {
        return html + footerHtml
    }
    return html.slice(0, bodyClose.index) + footerHtml + html.slice(bodyClose.index)
}

export function sandboxBlockedEventRedisConfig(connection: RedisConnectionConfig): RedisPoolConfig {
    return {
        connection: { ...connection, exitOnRepeatedErrors: false },
        poolMinSize: 0,
        poolMaxSize: MAX_OPEN_STORE_CALLS,
        acquireTimeoutMillis: EVENT_CAPTURE_TIMEOUT_MS,
    }
}

export class SandboxEmailSender {
    public readonly canSend: boolean

    constructor(
        public readonly config: SandboxEmailSenderConfig,
        private teamManager: TeamManager,
        private blockedEventRedis: Pick<RedisV2, 'useClient'>
    ) {
        this.config = {
            ...config,
            tenantName: config.tenantName.trim(),
            configurationSetName: config.configurationSetName.trim(),
            fromAddress: config.fromAddress.trim(),
        }
        const emptySettings = emptyRouteSettings(this.config)
        if (this.config.enabled && emptySettings.length) {
            logger.error('The sandbox sender is switched on with empty route settings, so it skips every send', {
                emptySettings,
            })
        }
        this.canSend = this.config.enabled && !emptySettings.length
    }

    public async buildSandboxMessage(
        params: CyclotronInvocationQueueParametersEmailType,
        senderName: string,
        teamId: number
    ): Promise<SandboxMessage> {
        if (!params.text && !params.html) {
            throw new Error(
                'The sandbox email template must include HTML or text content. Update the template and try again.'
            )
        }
        const team = await this.teamManager.getTeam(teamId)
        if (!team) {
            throw new Error('Could not identify the organization sending this sandbox email. Try again.')
        }
        const footer = `This email was sent by ${senderName} with the PostHog sandbox sender. Organization ID: ${team.organization_id}.`
        return {
            params: {
                ...params,
                from: { ...params.from, name: senderName, email: this.config.fromAddress },
                replyTo: undefined,
                preheader: undefined,
                ...(params.text ? { text: `${params.text}\n\n${footer}` } : {}),
                ...(params.html
                    ? { html: appendHtmlFooter(maybeAddPreheaderToEmail(params.html, params.preheader), footer) }
                    : {}),
            },
            headers: [{ Name: 'X-PostHog-Organization-Id', Value: team.organization_id }],
        }
    }

    public async captureSent(teamId: number, isTest: boolean, recipientCount: number): Promise<void> {
        await this.captureEvent(teamId, 'workflows sandbox email sent', {
            recipient_count: recipientCount,
            source: isTest ? 'test' : 'workflow',
            is_test: isTest,
        })
    }

    public async captureBlocked(
        teamId: number,
        isTest: boolean,
        reason: SandboxEmailBlockReason,
        blockedRecipientCount: number
    ): Promise<void> {
        sandboxEmailBlockedTotal.inc({ reason, is_test: String(isTest) })
        await this.captureEvent(
            teamId,
            'workflows sandbox email blocked',
            { reason, blocked_recipient_count: blockedRecipientCount, is_test: isTest },
            () => this.isFirstBlockInWindow(teamId, isTest, reason)
        )
    }

    private async captureEvent(
        teamId: number,
        event: string,
        properties: Record<string, string | number | boolean>,
        storeCheck?: () => Promise<boolean>
    ): Promise<void> {
        let timer: NodeJS.Timeout | undefined
        const deadline = new Promise<boolean>((resolve) => {
            timer = setTimeout(() => resolve(false), EVENT_CAPTURE_TIMEOUT_MS)
        })
        const capture = this.captureEventNow(teamId, event, properties, storeCheck).then(() => true)
        try {
            if (!(await Promise.race([capture, deadline]))) {
                logger.warn('Gave up capturing a sandbox email event: the event store did not answer', {
                    teamId,
                    event,
                })
            }
        } finally {
            clearTimeout(timer)
        }
    }

    private async captureEventNow(
        teamId: number,
        event: string,
        properties: Record<string, string | number | boolean>,
        storeCheck?: () => Promise<boolean>
    ): Promise<void> {
        try {
            if (storeCheck && !(await storeCheck())) {
                return
            }
            const team = await this.teamManager.getTeam(teamId)
            if (team) {
                captureTeamEvent(team, event, properties)
            }
        } catch (error) {
            logger.warn('Could not capture sandbox email event', { teamId, event, error })
        }
    }

    private async isFirstBlockInWindow(
        teamId: number,
        isTest: boolean,
        reason: SandboxEmailBlockReason
    ): Promise<boolean> {
        const firstBlock = await this.blockedEventRedis.useClient({ name: 'sandbox-blocked-event' }, (client) =>
            client.set(
                `@posthog/workflows-sandbox-blocked/${teamId}/${reason}/${isTest ? 'test' : 'live'}`,
                '1',
                'EX',
                BLOCKED_EVENT_WINDOW_SECONDS,
                'NX'
            )
        )
        return firstBlock === 'OK'
    }
}
