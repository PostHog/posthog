import { createHash } from 'crypto'
import { type DefaultTreeAdapterMap, defaultTreeAdapter, parse, serialize } from 'parse5'

import { CyclotronInvocationQueueParametersEmailType } from '~/cdp/schema/cyclotron'
import { logger } from '~/common/utils/logger'
import { captureTeamEvent } from '~/common/utils/posthog'
import { TeamManager } from '~/common/utils/team-manager'

import { ClaimRequest, RateLimiterService } from '../rate-limiter/rate-limiter.service'
import { maybeAddPreheaderToEmail } from './helpers/preheader'

const SECONDS_PER_DAY = 86400
const DAILY_CAP_TTL_SECONDS = 2 * SECONDS_PER_DAY

export interface SandboxEmailSenderConfig {
    enabled: boolean
    tenantName: string
    configurationSetName: string
    fromAddress: string
    dailyTeamCap: number
    dailyRecipientCap: number
}

export type SandboxDailyCapClaim =
    | { type: 'granted' }
    | { type: 'project_cap_reached' }
    | { type: 'recipient_cap_reached'; addresses: string[] }
    | { type: 'check_failed' }

type SandboxEmailOutcome =
    | { type: 'sent'; recipientCount: number }
    | {
          type: 'blocked'
          reason: 'switch_off' | 'recipient_not_member' | 'check_failed' | 'cap_reached'
          blockedRecipientCount: number
      }

function dailyBucket(key: string, requested: number, capacity: number): ClaimRequest {
    return { key, requested, capacity, refillPerSecond: capacity / SECONDS_PER_DAY, ttlSeconds: DAILY_CAP_TTL_SECONDS }
}

function isPositiveInteger(value: number): boolean {
    return Number.isInteger(value) && value > 0
}

// One `{teamId}` hash tag keeps every bucket of a claim in one Valkey cluster slot.
function dailyCapKeyPrefix(teamId: number): string {
    return `@posthog/workflows-sandbox-daily/{${teamId}}`
}

function addressDigest(address: string): string {
    return createHash('sha256').update(address.toLowerCase()).digest('hex')
}

function distinctAddresses(recipients: string[]): string[] {
    const addresses = new Map<string, string>()
    for (const recipient of recipients) {
        const trimmed = recipient.trim()
        const normalized = trimmed.toLowerCase()
        if (!addresses.has(normalized)) {
            addresses.set(normalized, trimmed)
        }
    }
    return [...addresses.values()]
}

function htmlBody(document: DefaultTreeAdapterMap['document']): DefaultTreeAdapterMap['element'] | undefined {
    const root = document.childNodes.find(defaultTreeAdapter.isElementNode)
    return root?.childNodes.find(
        (node): node is DefaultTreeAdapterMap['element'] =>
            defaultTreeAdapter.isElementNode(node) && node.tagName === 'body' && node.namespaceURI === root.namespaceURI
    )
}

function appendHtmlFooter(html: string, footer: string, preheader?: string): string {
    const preheaderText = defaultTreeAdapter.createDocumentFragment()
    defaultTreeAdapter.insertText(preheaderText, preheader ?? '')
    const document = parse(maybeAddPreheaderToEmail(html, serialize(preheaderText)), { scriptingEnabled: false })
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
    constructor(
        public readonly config: SandboxEmailSenderConfig,
        private teamManager: TeamManager,
        private dailyCapLimiter: RateLimiterService | null
    ) {}

    public async claimDailyCaps(teamId: number, recipients: string[]): Promise<SandboxDailyCapClaim> {
        const { dailyTeamCap, dailyRecipientCap } = this.config
        if (!this.dailyCapLimiter || !isPositiveInteger(dailyTeamCap) || !isPositiveInteger(dailyRecipientCap)) {
            logger.error('Sandbox email daily caps are not configured correctly', { teamId })
            return { type: 'check_failed' }
        }
        const addresses = distinctAddresses(recipients)
        const claim = await this.dailyCapLimiter.claimAllOrNothing([
            dailyBucket(`${dailyCapKeyPrefix(teamId)}/team`, recipients.length, dailyTeamCap),
            ...addresses.map((address) =>
                dailyBucket(`${dailyCapKeyPrefix(teamId)}/recipient/${addressDigest(address)}`, 1, dailyRecipientCap)
            ),
        ])
        if (claim.granted) {
            return { type: 'granted' }
        }
        if (claim.deniedIndexes === null) {
            return { type: 'check_failed' }
        }
        if (claim.deniedIndexes.includes(0)) {
            return { type: 'project_cap_reached' }
        }
        return { type: 'recipient_cap_reached', addresses: claim.deniedIndexes.map((index) => addresses[index - 1]) }
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

    public async capture(teamId: number, isTest: boolean, outcome: SandboxEmailOutcome): Promise<void> {
        try {
            const team = await this.teamManager.getTeam(teamId)
            if (team) {
                const properties =
                    outcome.type === 'sent'
                        ? { recipient_count: outcome.recipientCount, source: isTest ? 'test' : 'workflow' }
                        : { reason: outcome.reason, blocked_recipient_count: outcome.blockedRecipientCount }
                captureTeamEvent(team, `workflows sandbox email ${outcome.type}`, { ...properties, is_test: isTest })
            }
        } catch (error) {
            logger.warn('Could not capture sandbox email event', { teamId, error })
        }
    }
}
