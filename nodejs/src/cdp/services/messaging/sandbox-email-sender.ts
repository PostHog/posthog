import { type DefaultTreeAdapterMap, defaultTreeAdapter, parse, parseFragment, serialize } from 'parse5'

import { CyclotronInvocationQueueParametersEmailType } from '~/cdp/schema/cyclotron'
import { RedisV2 } from '~/common/redis/redis-v2'
import { RedisConnectionConfig, RedisPoolConfig } from '~/common/utils/db/redis'
import { logger } from '~/common/utils/logger'
import { captureTeamEvent } from '~/common/utils/posthog'
import { TeamManager } from '~/common/utils/team-manager'

import { DeadlineSlots } from '../../utils/deadline-slots'
import { maybeAddPreheaderToEmail } from './helpers/preheader'

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
        .filter((setting) => !config[setting].trim())
        .map((setting) => ROUTE_SETTING_NAMES[setting])
}

export type SandboxEmailBlockReason = 'switch_off' | 'recipient_not_member' | 'recipient_unverified' | 'check_failed'

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
        'display:block!important;position:static!important;margin:0!important;overflow:visible!important;height:auto!important;max-height:none!important;clip:auto!important;clip-path:none!important;transform:none!important;opacity:1!important;visibility:visible!important;filter:none!important;contain:none!important;content-visibility:visible!important;zoom:1!important'
    for (const ancestor of [root, body]) {
        const style = ancestor.attrs.find((attribute) => attribute.name === 'style')
        if (style) {
            style.value = [...completeDeclarations(style.value), visibleLayout].join(';')
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

export function sandboxBlockedEventRedisConfig(connection: RedisConnectionConfig): RedisPoolConfig {
    return {
        // Blocked events are optional telemetry, so a store that refuses these connections must not stop the worker.
        // A call that gets no answer ends at the capture deadline, so a stalled store frees its slot.
        connection: {
            ...connection,
            options: { ...connection.options, commandTimeout: EVENT_CAPTURE_TIMEOUT_MS },
            exitOnRepeatedErrors: false,
        },
        poolMinSize: 0,
        poolMaxSize: MAX_OPEN_STORE_CALLS,
    }
}

export class SandboxEmailSender {
    public readonly canSend: boolean
    private storeSlots = new DeadlineSlots(MAX_OPEN_STORE_CALLS)

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
        const emptySettings = emptyRouteSettings(config)
        if (config.enabled && emptySettings.length) {
            logger.error('The sandbox sender is switched on with empty route settings, so it skips every send', {
                emptySettings,
            })
        }
        this.canSend = config.enabled && !emptySettings.length
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
