import { createHash } from 'crypto'
import { type DefaultTreeAdapterMap, defaultTreeAdapter, parse, parseFragment, serialize } from 'parse5'

import { CyclotronInvocationQueueParametersEmailType } from '~/cdp/schema/cyclotron'
import { RedisV2 } from '~/common/redis/redis-v2'
import { logger } from '~/common/utils/logger'
import { captureTeamEvent } from '~/common/utils/posthog'
import { TeamManager } from '~/common/utils/team-manager'

import { SandboxSenderStateService } from '../managers/sandbox-sender-state.service'
import { ClaimRequest, IssuedClaim, RateLimiterService } from '../rate-limiter/rate-limiter.service'
import { maybeAddPreheaderToEmail } from './helpers/preheader'

const SECONDS_PER_DAY = 86400
const DAILY_CAP_TTL_SECONDS = 2 * SECONDS_PER_DAY

export interface SandboxEmailSenderConfig {
    enabled: boolean
    tenantName: string
    configurationSetName: string
    fromAddress: string
    dailyTeamCap: string
    dailyRecipientCap: string
}

const ROUTE_SETTING_NAMES = {
    tenantName: 'SES_SANDBOX_TENANT_NAME',
    configurationSetName: 'SES_SANDBOX_CONFIGURATION_SET',
    fromAddress: 'SES_SANDBOX_FROM_ADDRESS',
} as const

function emptyRouteSettings(config: SandboxEmailSenderConfig): string[] {
    return (Object.keys(ROUTE_SETTING_NAMES) as (keyof typeof ROUTE_SETTING_NAMES)[])
        .filter((setting) => !config[setting].trim())
        .map((setting) => ROUTE_SETTING_NAMES[setting])
}

export type SandboxEmailBlockReason =
    | 'switch_off'
    | 'recipient_not_member'
    | 'recipient_unverified'
    | 'check_failed'
    | 'cap_reached'
    | 'paused'

export type SandboxDailyCapGrant = { type: 'granted'; claim: IssuedClaim; buckets: ClaimRequest[] }

export type SandboxDailyCapClaim =
    | SandboxDailyCapGrant
    | { type: 'project_cap_reached' }
    | { type: 'recipient_cap_reached'; addresses: string[] }
    | { type: 'check_failed' }

function dailyBucket(key: string, requested: number, capacity: number): ClaimRequest {
    return { key, requested, capacity, refillPerSecond: capacity / SECONDS_PER_DAY, ttlSeconds: DAILY_CAP_TTL_SECONDS }
}

function parseDailyCap(value: string): number | null {
    const cap = /^\d+$/.test(value) ? Number(value) : null
    return cap !== null && Number.isSafeInteger(cap) && cap > 0 ? cap : null
}

// The organization hash tag keeps the project and recipient buckets in one Valkey cluster slot.
function dailyCapKeyPrefix(organizationId: string): string {
    return `@posthog/workflows-sandbox-daily/{${organizationId}}`
}

function addressDigest(address: string): string {
    return createHash('sha256').update(address.toLowerCase()).digest('hex')
}

function distinctAddresses(recipients: string[]): string[] {
    const addresses = new Map<string, string>()
    for (const recipient of recipients) {
        const trimmed = recipient.trim()
        if (!addresses.has(trimmed.toLowerCase())) {
            addresses.set(trimmed.toLowerCase(), trimmed)
        }
    }
    return [...addresses.values()]
}

const BLOCKED_EVENT_WINDOW_SECONDS = 3600

function htmlBody(document: DefaultTreeAdapterMap['document']): DefaultTreeAdapterMap['element'] | undefined {
    const root = document.childNodes.find(defaultTreeAdapter.isElementNode)
    return root?.childNodes.find(
        (node): node is DefaultTreeAdapterMap['element'] =>
            defaultTreeAdapter.isElementNode(node) && node.tagName === 'body' && node.namespaceURI === root.namespaceURI
    )
}

function protectFooterAncestors(
    document: DefaultTreeAdapterMap['document'],
    body: DefaultTreeAdapterMap['element']
): void {
    const root = document.childNodes.find(defaultTreeAdapter.isElementNode)!
    const visibleLayout =
        'display:block!important;position:static!important;overflow:visible!important;height:auto!important;max-height:none!important;clip:auto!important;clip-path:none!important;transform:none!important;opacity:1!important;visibility:visible!important;filter:none!important;contain:none!important;content-visibility:visible!important;zoom:1!important'
    for (const ancestor of [root, body]) {
        const style = ancestor.attrs.find((attribute) => attribute.name === 'style')
        if (style) {
            style.value = `${style.value};${visibleLayout}`
        } else {
            ancestor.attrs.push({ name: 'style', value: visibleLayout })
        }
    }
}

function appendHtmlFooter(html: string, footer: string, preheader?: string): string {
    const preheaderText = parseFragment(preheader ?? '', { scriptingEnabled: false })
    const document = parse(maybeAddPreheaderToEmail(html, serialize(preheaderText, { scriptingEnabled: false })), {
        scriptingEnabled: false,
    })
    const body = htmlBody(document)
    if (!body) {
        throw new Error('The sandbox email template must have an HTML body. Update the template and try again.')
    }
    const nodes: DefaultTreeAdapterMap['childNode'][] = [...document.childNodes]
    for (const node of nodes) {
        if (defaultTreeAdapter.isElementNode(node)) {
            if (node.tagName === 'plaintext' && node.namespaceURI === body.namespaceURI) {
                node.tagName = 'pre'
            }
            if (node.tagName === 'noscript' && node.namespaceURI === body.namespaceURI) {
                node.tagName = 'div'
            }
            nodes.push(...node.childNodes)
            if (node.tagName === 'template' && node.namespaceURI === body.namespaceURI) {
                nodes.push(
                    ...defaultTreeAdapter.getTemplateContent(node as DefaultTreeAdapterMap['template']).childNodes
                )
            }
        }
    }
    protectFooterAncestors(document, body)
    const paragraph = defaultTreeAdapter.createElement('div', body.namespaceURI, [
        {
            name: 'style',
            value: 'all:initial!important;display:block!important;visibility:visible!important;opacity:1!important;font:12px sans-serif!important;color:#525252!important;background:#fff!important;padding:16px 0!important',
        },
    ])
    defaultTreeAdapter.insertText(paragraph, footer)
    defaultTreeAdapter.appendChild(body, paragraph)
    const serialized = serialize(document, { scriptingEnabled: false })
    for (const scriptingEnabled of [false, true]) {
        const deliveredFooter = htmlBody(parse(serialized, { scriptingEnabled }))?.childNodes.at(-1)
        if (
            !deliveredFooter ||
            !defaultTreeAdapter.isElementNode(deliveredFooter) ||
            deliveredFooter.tagName !== 'div' ||
            deliveredFooter.namespaceURI !== body.namespaceURI ||
            deliveredFooter.attrs.find((attribute) => attribute.name === 'style')?.value !== paragraph.attrs[0].value ||
            deliveredFooter.childNodes.length !== 1 ||
            !defaultTreeAdapter.isTextNode(deliveredFooter.childNodes[0]) ||
            deliveredFooter.childNodes[0].value !== footer
        ) {
            throw new Error(
                'The sandbox email template could not retain its identification footer. Update the template and try again.'
            )
        }
    }
    return serialized
}

export class SandboxEmailSender {
    public readonly canSend: boolean

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
        const emptySettings = emptyRouteSettings(config)
        if (config.enabled && emptySettings.length) {
            logger.error('The sandbox sender is switched on with empty route settings, so it skips every send', {
                emptySettings,
            })
        }
        this.canSend = config.enabled && !emptySettings.length
    }

    public async pauseGate(): Promise<'open' | 'paused' | 'check_failed'> {
        try {
            return (await this.senderState.isPaused(this.config.tenantName)) ? 'paused' : 'open'
        } catch (error) {
            logger.warn('Could not check the sandbox sender pause state', { error })
            return 'check_failed'
        }
    }

    public async claimDailyCaps(teamId: number, recipients: string[]): Promise<SandboxDailyCapClaim> {
        const dailyTeamCap = parseDailyCap(this.config.dailyTeamCap)
        const dailyRecipientCap = parseDailyCap(this.config.dailyRecipientCap)
        if (!this.dailyCapLimiter || dailyTeamCap === null || dailyRecipientCap === null) {
            logger.error('Sandbox email daily caps are not configured correctly', { teamId })
            return { type: 'check_failed' }
        }
        const team = await this.teamManager.getTeam(teamId)
        if (!team) {
            return { type: 'check_failed' }
        }
        const prefix = dailyCapKeyPrefix(team.organization_id)
        const addresses = distinctAddresses(recipients)
        const buckets = [
            dailyBucket(`${prefix}/project/${teamId}`, recipients.length, dailyTeamCap),
            ...addresses.map((address) =>
                dailyBucket(`${prefix}/recipient/${addressDigest(address)}`, 1, dailyRecipientCap)
            ),
        ]
        const claim = await this.dailyCapLimiter.claimAllOrNothing(buckets)
        if (claim.granted) {
            return { type: 'granted', claim, buckets }
        }
        if (claim.deniedIndexes === null) {
            return { type: 'check_failed' }
        }
        if (claim.deniedIndexes.includes(0)) {
            return { type: 'project_cap_reached' }
        }
        return { type: 'recipient_cap_reached', addresses: claim.deniedIndexes.map((index) => addresses[index - 1]) }
    }

    public async returnDailyCaps(grant: SandboxDailyCapGrant): Promise<void> {
        await this.dailyCapLimiter?.returnClaim(grant.claim, grant.buckets)
    }

    public async withIdentificationFooter(
        params: CyclotronInvocationQueueParametersEmailType,
        senderName: string,
        teamId: number
    ): Promise<CyclotronInvocationQueueParametersEmailType> {
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
            ...params,
            from: { ...params.from, name: senderName, email: this.config.fromAddress },
            replyTo: undefined,
            preheader: undefined,
            ...(params.text ? { text: `${params.text}\n\n${footer}` } : {}),
            ...(params.html ? { html: appendHtmlFooter(params.html, footer, params.preheader) } : {}),
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
        })
    }

    public async captureBlocked(
        teamId: number,
        isTest: boolean,
        reason: SandboxEmailBlockReason,
        blockedRecipientCount: number
    ): Promise<void> {
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
        shouldCapture: () => Promise<boolean> = () => Promise.resolve(true)
    ): Promise<void> {
        try {
            if (!(await shouldCapture())) {
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
        const firstBlock = await this.blockedEventRedis.useClient(
            { name: 'sandbox-blocked-event', timeout: 1000 },
            (client) =>
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
