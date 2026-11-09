import { MessageHeader } from '@aws-sdk/client-sesv2'
import { createHash } from 'crypto'
import { Counter } from 'prom-client'

import { CyclotronInvocationQueueParametersEmailType } from '~/cdp/schema/cyclotron'
import { RedisV2 } from '~/common/redis/redis-v2'
import { RedisConnectionConfig, RedisPoolConfig } from '~/common/utils/db/redis'
import { logger } from '~/common/utils/logger'
import { captureTeamEvent } from '~/common/utils/posthog'
import { TeamManager } from '~/common/utils/team-manager'

import { SandboxSenderStateService } from '../managers/sandbox-sender-state.service'
import { ClaimOutcome, ClaimRequest, IssuedClaim, RateLimiterService } from '../rate-limiter/rate-limiter.service'
import { escapeHtml } from './helpers/escape-html'
import { maybeAddPreheaderToEmail } from './helpers/preheader'

const SECONDS_PER_DAY = 86400
const DAILY_CAP_TTL_SECONDS = 2 * SECONDS_PER_DAY
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
    dailyTeamCap: number
    dailyRecipientCap: number
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
    | 'recipient_cap_reached'
    | 'project_cap_reached'
    | 'cap_check_failed'
    | 'paused'
    | 'pause_check_failed'
    | 'organization_blocked'

const sandboxEmailBlockedTotal = new Counter({
    name: 'cdp_sandbox_email_blocked_total',
    help: 'Sandbox sender sends skipped before delivery, by block reason and by whether the send was a test send.',
    labelNames: ['reason', 'is_test'],
})

export type SandboxDailyCapGrant = { type: 'granted'; claim: IssuedClaim }

export type SandboxDailyCapClaim =
    | SandboxDailyCapGrant
    | { type: 'project_cap_reached' }
    | { type: 'recipient_cap_reached'; addresses: string[] }
    | { type: 'cap_check_failed' }

function dailyBucket(key: string, requested: number, capacity: number): ClaimRequest {
    return { key, requested, capacity, refillPerSecond: capacity / SECONDS_PER_DAY, ttlSeconds: DAILY_CAP_TTL_SECONDS }
}

function validDailyCap(cap: number): number | null {
    return Number.isSafeInteger(cap) && cap > 0 ? cap : null
}

function dailyCapKeyPrefix(organizationId: string): string {
    return `@posthog/workflows-sandbox-daily/{${organizationId}}`
}

function addressDigest(address: string): string {
    return createHash('sha256').update(address.toLowerCase()).digest('hex')
}

function deliveredCopiesByAddress(recipients: string[]): { address: string; copies: number }[] {
    const addresses = new Map<string, { address: string; copies: number }>()
    for (const recipient of recipients) {
        const address = recipient.trim()
        const entry = addresses.get(address.toLowerCase())
        if (entry) {
            entry.copies += 1
        } else {
            addresses.set(address.toLowerCase(), { address, copies: 1 })
        }
    }
    return [...addresses.values()]
}

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
    private readonly dailyCaps: { team: number; recipient: number } | null

    constructor(
        public readonly config: SandboxEmailSenderConfig,
        private teamManager: TeamManager,
        private blockedEventRedis: Pick<RedisV2, 'useClient'>,
        private dailyCapLimiter: RateLimiterService | null,
        private senderState: Pick<SandboxSenderStateService, 'isPaused'>
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
        const team = validDailyCap(config.dailyTeamCap)
        const recipient = validDailyCap(config.dailyRecipientCap)
        this.dailyCaps = team !== null && recipient !== null ? { team, recipient } : null
        if (this.config.enabled && !this.dailyCaps) {
            logger.error('Sandbox email daily caps are not configured correctly, so every cap check fails')
        }
    }

    public async pauseGate({ fresh = false }: { fresh?: boolean } = {}): Promise<'open' | 'paused' | 'check_failed'> {
        try {
            return (await this.senderState.isPaused({ fresh })) ? 'paused' : 'open'
        } catch (error) {
            logger.warn('Could not check the sandbox sender pause state', { error })
            return 'check_failed'
        }
    }

    public async claimDailyCaps(teamId: number, recipients: string[]): Promise<SandboxDailyCapClaim> {
        if (!this.dailyCapLimiter) {
            logger.warn('Sandbox email daily caps have no Valkey pool on this consumer, so the cap check fails')
            return { type: 'cap_check_failed' }
        }
        if (!this.dailyCaps) {
            return { type: 'cap_check_failed' }
        }
        const { team: dailyTeamCap, recipient: dailyRecipientCap } = this.dailyCaps
        const addresses = deliveredCopiesByAddress(recipients)
        let claim: ClaimOutcome
        try {
            const team = await this.teamManager.getTeam(teamId)
            if (!team) {
                return { type: 'cap_check_failed' }
            }
            const prefix = dailyCapKeyPrefix(team.organization_id)
            claim = await this.dailyCapLimiter.claimRefundable([
                dailyBucket(`${prefix}/project/${teamId}`, recipients.length, dailyTeamCap),
                ...addresses.map(({ address, copies }) =>
                    dailyBucket(`${prefix}/recipient/${addressDigest(address)}`, copies, dailyRecipientCap)
                ),
            ])
        } catch (error) {
            logger.warn('Could not check sandbox email daily caps', { teamId, error: String(error) })
            return { type: 'cap_check_failed' }
        }
        if (claim.granted) {
            return { type: 'granted', claim }
        }
        if (claim.deniedIndexes === null) {
            return { type: 'cap_check_failed' }
        }
        if (claim.deniedIndexes.includes(0)) {
            return { type: 'project_cap_reached' }
        }
        return {
            type: 'recipient_cap_reached',
            addresses: claim.deniedIndexes.map((index) => addresses[index - 1].address),
        }
    }

    public async returnDailyCaps(grant: SandboxDailyCapGrant): Promise<void> {
        await this.dailyCapLimiter?.returnClaim(grant.claim)
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

    public async captureDelivered(teamId: number, isTest: boolean, recipientCount: number): Promise<void> {
        await this.captureEvent(teamId, 'workflows sandbox email delivered', {
            recipient_count: recipientCount,
            is_test: isTest,
            source: isTest ? 'test' : 'workflow',
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
