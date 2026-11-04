import { createHash } from 'crypto'
import {
    type DefaultTreeAdapterMap,
    defaultTreeAdapter,
    html as htmlSpec,
    parse,
    parseFragment,
    serialize,
    serializeOuter,
} from 'parse5'

import { CyclotronInvocationQueueParametersEmailType } from '~/cdp/schema/cyclotron'
import { RedisV2 } from '~/common/redis/redis-v2'
import { RedisConnectionConfig, RedisPoolConfig } from '~/common/utils/db/redis'
import { logger } from '~/common/utils/logger'
import { captureTeamEvent } from '~/common/utils/posthog'
import { TeamManager } from '~/common/utils/team-manager'

import { DeadlineSlots } from '../../utils/deadline-slots'
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
    | 'recipient_cap_reached'
    | 'project_cap_reached'
    | 'cap_check_failed'
    | 'paused'
    | 'pause_check_failed'

export type SandboxDailyCapGrant = { type: 'granted'; claim: IssuedClaim }

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
// The send is already decided when this runs, and the worker's batch waits for it, so a stalled
// store must not hold the invocation open.
const EVENT_CAPTURE_TIMEOUT_MS = 1000
// The deadline cannot cancel a store call, so a stalled call keeps its connection until the store answers.
// At most this many run at once, on a pool of their own this size; a capture waiting for a slot holds
// nothing and gives up at its deadline, so a burst against a healthy store keeps every event.
export const MAX_OPEN_STORE_CALLS = 10

function htmlBody(document: DefaultTreeAdapterMap['document']): DefaultTreeAdapterMap['element'] | undefined {
    const root = document.childNodes.find(defaultTreeAdapter.isElementNode)
    return root?.childNodes.find(
        (node): node is DefaultTreeAdapterMap['element'] =>
            defaultTreeAdapter.isElementNode(node) && node.tagName === 'body' && node.namespaceURI === root.namespaceURI
    )
}

const BRACKET_CLOSERS: Record<string, string> = { '(': ')', '[': ']', '{': '}' }

// Keeps only the template's complete declarations, so nothing it leaves open (a comment, string or
// bracket) can swallow the overrides appended after them. Scanning stops at an escape or at a line
// break inside a string, where a browser could tokenize the rest differently.
function completeDeclarations(style: string): string[] {
    return scanDeclarations(style).filter((declaration) => declaration.includes(':') && !/[{}]/.test(declaration))
}

const QUOTES = ['"', "'"]

// Index scans, not regexes: the style is user content, and a backtracking pattern stalls the worker on it.
function skipSpaces(text: string, index: number): number {
    while (index < text.length && /\s/.test(text[index])) {
        index++
    }
    return index
}

// The index of the `)` that ends an unquoted url(), or -1 when the token is a bad url.
function unquotedUrlEnd(style: string, start: number): number {
    let index = skipSpaces(style, start)
    while (index < style.length && !/["'()\\\s]/.test(style[index])) {
        index++
    }
    index = skipSpaces(style, index)
    return style[index] === ')' ? index : -1
}

function scanDeclarations(style: string): string[] {
    const declarations: string[] = []
    const closers: string[] = []
    let quote: string | null = null
    let current = ''
    for (let index = 0; index < style.length; index++) {
        const char = style[index]
        if (char === '\\' || (quote && /[\n\r\f]/.test(char))) {
            return declarations
        }
        if (quote) {
            current += char
            quote = char === quote ? null : quote
        } else if (char === '/' && style[index + 1] === '*') {
            const end = style.indexOf('*/', index + 2)
            if (end === -1) {
                return declarations
            }
            // A comment separates tokens, so it becomes a space: dropping it could join a slash and a star.
            current += ' '
            index = end + 1
        } else if (
            char === '(' &&
            style.slice(index - 3, index).toLowerCase() === 'url' &&
            !QUOTES.includes(style[skipSpaces(style, index + 1)])
        ) {
            // An unquoted url() is one token that ends at `)`. A quote, bracket, escape or inner space
            // makes it a bad url, which a browser reads differently from this scanner.
            const end = unquotedUrlEnd(style, index + 1)
            if (end === -1) {
                return declarations
            }
            current += style.slice(index, end + 1)
            index = end
        } else if (char === ';' && !closers.length) {
            declarations.push(current)
            current = ''
        } else {
            if (char === '"' || char === "'") {
                quote = char
            } else if (BRACKET_CLOSERS[char]) {
                closers.push(BRACKET_CLOSERS[char])
            } else if (char === closers.at(-1)) {
                closers.pop()
            }
            current += char
        }
    }
    if (!quote && !closers.length) {
        declarations.push(current)
    }
    return declarations
}

function protectFooterAncestors(
    document: DefaultTreeAdapterMap['document'],
    body: DefaultTreeAdapterMap['element']
): void {
    const root = document.childNodes.find(defaultTreeAdapter.isElementNode)!
    const visibleLayout =
        'display:block!important;position:static!important;margin:0!important;overflow:visible!important;height:auto!important;max-height:none!important;clip:auto!important;clip-path:none!important;transform:none!important;opacity:1!important;visibility:visible!important;filter:none!important;contain:none!important;content-visibility:visible!important;mask:none!important;-webkit-mask:none!important;mix-blend-mode:normal!important;translate:none!important;scale:none!important;rotate:none!important;zoom:1!important'
    for (const ancestor of [root, body]) {
        const style = ancestor.attrs.find((attribute) => attribute.name === 'style')
        if (style) {
            style.value = [...completeDeclarations(style.value), visibleLayout].join(';')
        } else {
            ancestor.attrs.push({ name: 'style', value: visibleLayout })
        }
    }
}

// A plaintext element swallows everything after it, and noscript content parses differently once scripting
// is on, so neither may reach the delivered email in a form that can hide the footer.
function neutralizeRawTextElements(roots: DefaultTreeAdapterMap['childNode'][]): void {
    const nodes = [...roots]
    for (const node of nodes) {
        if (defaultTreeAdapter.isElementNode(node)) {
            if (node.tagName === 'plaintext' && node.namespaceURI === htmlSpec.NS.HTML) {
                node.tagName = 'pre'
            }
            if (node.tagName === 'noscript' && node.namespaceURI === htmlSpec.NS.HTML) {
                node.tagName = 'div'
            }
            nodes.push(...node.childNodes)
            if (node.tagName === 'template' && node.namespaceURI === htmlSpec.NS.HTML) {
                nodes.push(
                    ...defaultTreeAdapter.getTemplateContent(node as DefaultTreeAdapterMap['template']).childNodes
                )
            }
        }
    }
}

function leavesOutlookConditionalOpen(html: string): boolean {
    let depth = 0
    for (const match of html.matchAll(/<!(?:--)?\[(if\b|endif\])/gi)) {
        depth = match[1].toLowerCase() === 'if' ? depth + 1 : Math.max(depth - 1, 0)
    }
    return depth > 0
}

function appendHtmlFooter(html: string, footer: string, preheader?: string): string {
    const preheaderText = parseFragment(preheader ?? '', { scriptingEnabled: false })
    neutralizeRawTextElements(preheaderText.childNodes)
    const document = parse(maybeAddPreheaderToEmail(html, serialize(preheaderText, { scriptingEnabled: false })), {
        scriptingEnabled: false,
    })
    const body = htmlBody(document)
    if (!body) {
        throw new Error('The sandbox email template must have an HTML body. Update the template and try again.')
    }
    neutralizeRawTextElements(document.childNodes)
    protectFooterAncestors(document, body)
    const paragraph = defaultTreeAdapter.createElement('div', body.namespaceURI, [
        {
            name: 'style',
            value: 'all:initial!important;display:block!important;visibility:visible!important;opacity:1!important;position:relative!important;z-index:2147483647!important;inset:auto!important;float:none!important;width:auto!important;max-width:none!important;min-width:0!important;height:auto!important;max-height:none!important;overflow:visible!important;margin:0!important;transform:none!important;translate:none!important;scale:none!important;rotate:none!important;clip-path:none!important;filter:none!important;mask:none!important;-webkit-mask:none!important;mix-blend-mode:normal!important;text-indent:0!important;letter-spacing:normal!important;word-spacing:normal!important;text-transform:none!important;text-shadow:none!important;white-space:normal!important;font:12px sans-serif!important;color:#525252!important;background:#fff!important;padding:16px 0!important',
        },
    ])
    defaultTreeAdapter.insertText(paragraph, footer)
    defaultTreeAdapter.appendChild(body, paragraph)
    const serialized = serialize(document, { scriptingEnabled: false })
    if (leavesOutlookConditionalOpen(serialized)) {
        throw new Error(
            'The sandbox email template could not retain its identification footer. Update the template and try again.'
        )
    }
    for (const scriptingEnabled of [false, true]) {
        const deliveredFooter = htmlBody(parse(serialized, { scriptingEnabled }))?.childNodes.at(-1)
        if (
            !deliveredFooter ||
            !defaultTreeAdapter.isElementNode(deliveredFooter) ||
            deliveredFooter.namespaceURI !== body.namespaceURI ||
            serializeOuter(deliveredFooter) !== serializeOuter(paragraph)
        ) {
            throw new Error(
                'The sandbox email template could not retain its identification footer. Update the template and try again.'
            )
        }
    }
    return serialized
}

export function sandboxBlockedEventRedisConfig(connection: RedisConnectionConfig): RedisPoolConfig {
    return {
        // Blocked events are optional telemetry, so a store that refuses these connections must not stop the worker.
        // No command timeout: a timed-out command stays queued on its connection while its slot frees, so a store
        // that stops answering would collect commands without limit. A stalled call keeps its slot instead.
        connection: { ...connection, exitOnRepeatedErrors: false },
        poolMinSize: 0,
        poolMaxSize: MAX_OPEN_STORE_CALLS,
    }
}

export class SandboxEmailSender {
    public readonly canSend: boolean
    private storeSlots = new DeadlineSlots(MAX_OPEN_STORE_CALLS)
    private dailyCaps: { team: number; recipient: number } | null

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
        const team = parseDailyCap(config.dailyTeamCap)
        const recipient = parseDailyCap(config.dailyRecipientCap)
        this.dailyCaps = dailyCapLimiter && team !== null && recipient !== null ? { team, recipient } : null
        if (config.enabled && !this.dailyCaps) {
            logger.error('Sandbox email daily caps are not configured correctly, so every cap check fails')
        }
    }

    public async pauseGate({ fresh = false }: { fresh?: boolean } = {}): Promise<'open' | 'paused' | 'check_failed'> {
        try {
            return (await this.senderState.isPaused(this.config.tenantName, { fresh })) ? 'paused' : 'open'
        } catch (error) {
            logger.warn('Could not check the sandbox sender pause state', { error })
            return 'check_failed'
        }
    }

    public async claimDailyCaps(teamId: number, recipients: string[]): Promise<SandboxDailyCapClaim> {
        if (!this.dailyCapLimiter || !this.dailyCaps) {
            return { type: 'check_failed' }
        }
        const { team: dailyTeamCap, recipient: dailyRecipientCap } = this.dailyCaps
        const addresses = distinctAddresses(recipients)
        // Members may store one address in two cases, and a mail server can treat each case as its own
        // mailbox, so the project allowance counts each distinct spelling as one email.
        const emails = new Set(recipients.map((recipient) => recipient.trim())).size
        let claim: Awaited<ReturnType<RateLimiterService['claimAllOrNothing']>>
        try {
            const team = await this.teamManager.getTeam(teamId)
            if (!team) {
                return { type: 'check_failed' }
            }
            const prefix = dailyCapKeyPrefix(team.organization_id)
            claim = await this.dailyCapLimiter.claimAllOrNothing([
                dailyBucket(`${prefix}/project/${teamId}`, emails, dailyTeamCap),
                ...addresses.map((address) =>
                    dailyBucket(`${prefix}/recipient/${addressDigest(address)}`, 1, dailyRecipientCap)
                ),
            ])
        } catch (error) {
            logger.warn('Could not check sandbox email daily caps', { teamId, error: String(error) })
            return { type: 'check_failed' }
        }
        if (claim.granted) {
            return { type: 'granted', claim }
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
        await this.dailyCapLimiter?.returnClaim(grant.claim)
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
            source: isTest ? 'test' : 'workflow',
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
        storeCheck?: () => Promise<boolean>
    ): Promise<void> {
        let timer: NodeJS.Timeout | undefined
        const deadline = new Promise<void>((resolve) => {
            timer = setTimeout(resolve, EVENT_CAPTURE_TIMEOUT_MS)
        })
        const captureNow = (): Promise<void> => this.captureEventNow(teamId, event, properties, storeCheck)
        const capture = storeCheck ? this.storeSlots.run(deadline, captureNow) : captureNow()
        try {
            if ((await Promise.race([capture.then(() => true), deadline.then(() => false)])) === false) {
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
