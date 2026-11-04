import { randomUUID } from 'crypto'
import {
    type DefaultTreeAdapterMap,
    Parser,
    type TreeAdapter,
    defaultTreeAdapter,
    html as htmlSpec,
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
import { maybeAddPreheaderToEmail } from './helpers/preheader'

const MAX_TEMPLATE_HTML_BYTES = 75_000
const MAX_ELEMENT_DEPTH = 256
const MAX_ATTRIBUTES_PER_TAG = 64
const MAX_CONDITION_LENGTH = 100

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
        'display:block!important;position:static!important;margin:0!important;overflow:visible!important;height:auto!important;max-height:none!important;clip:auto!important;clip-path:none!important;transform:none!important;opacity:1!important;visibility:visible!important;filter:none!important;contain:none!important;content-visibility:visible!important;mask:none!important;-webkit-mask:none!important;mix-blend-mode:normal!important;translate:none!important;scale:none!important;rotate:none!important;zoom:1!important;mso-hide:none!important'
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

function leavesOutlookConditionalOpen(roots: DefaultTreeAdapterMap['childNode'][]): boolean {
    let depth = 0
    const pending = [...roots].reverse()
    while (pending.length) {
        const node = pending.pop()!
        if (defaultTreeAdapter.isCommentNode(node)) {
            for (const match of `<!--${node.data}-->`.matchAll(/<!(?:--)?\[(?:(if)\b|endif\](?:--)?>)/gi)) {
                depth = match[1] ? depth + 1 : Math.max(depth - 1, 0)
            }
        } else if (defaultTreeAdapter.isElementNode(node)) {
            const children =
                node.tagName === 'template' && node.namespaceURI === htmlSpec.NS.HTML
                    ? defaultTreeAdapter.getTemplateContent(node as DefaultTreeAdapterMap['template']).childNodes
                    : node.childNodes
            pending.push(...[...children].reverse())
        }
    }
    return depth > 0
}

type ConditionalClient = { mso: number | null; ie: number | null }

const CONDITIONAL_CLIENTS: ConditionalClient[] = [
    ...[9, 10, 11, 12, 14, 15, 16].map((mso) => ({ mso, ie: null })),
    ...[5, 6, 7, 8, 9].map((ie) => ({ mso: null, ie })),
]

type ConditionalMarker =
    | { kind: 'hidden'; condition: string; content: string }
    | { kind: 'open'; condition: string }
    | { kind: 'close' }

class UnreadableConditional extends Error {}

function conditionHolds(condition: string, client: ConditionalClient): boolean {
    if (condition.length > MAX_CONDITION_LENGTH) {
        throw new UnreadableConditional()
    }
    const tokens = condition.match(/\(|\)|!|&|\||[a-z]+|\d+(?:\.\d+)?/gi) ?? []
    if (tokens.join('') !== condition.replace(/\s+/g, '')) {
        throw new UnreadableConditional()
    }
    let position = 0
    const next = (): string | undefined => tokens[position]
    const take = (): string => {
        const token = tokens[position++]
        if (token === undefined) {
            throw new UnreadableConditional()
        }
        return token
    }
    const comparison = (): boolean => {
        let operator = take().toLowerCase()
        let feature = operator
        if (['gt', 'gte', 'lt', 'lte'].includes(operator)) {
            feature = take().toLowerCase()
        } else {
            operator = 'eq'
        }
        const version =
            feature === 'mso'
                ? client.mso
                : feature === 'ie'
                  ? client.ie
                  : feature === 'vml'
                    ? client.mso && 1
                    : undefined
        if (version === undefined) {
            throw new UnreadableConditional()
        }
        const wanted = /^\d/.test(next() ?? '') ? Number(take()) : null
        if (version === null) {
            return false
        }
        if (wanted === null) {
            if (operator !== 'eq') {
                throw new UnreadableConditional()
            }
            return true
        }
        const comparisons: Record<string, boolean> = {
            eq: Math.floor(version) === Math.floor(wanted),
            gt: version > wanted,
            gte: version >= wanted,
            lt: version < wanted,
            lte: version <= wanted,
        }
        return comparisons[operator]
    }
    const unary = (): boolean => {
        if (next() === '!') {
            take()
            return !unary()
        }
        if (next() === '(') {
            take()
            const value = either()
            if (take() !== ')') {
                throw new UnreadableConditional()
            }
            return value
        }
        return comparison()
    }
    const both = (): boolean => {
        let value = unary()
        while (next() === '&') {
            take()
            value = unary() && value
        }
        return value
    }
    const either = (): boolean => {
        let value = both()
        while (next() === '|') {
            take()
            value = both() || value
        }
        return value
    }
    const value = either()
    if (position !== tokens.length) {
        throw new UnreadableConditional()
    }
    return value
}

class AttributeBoundedParser extends Parser<DefaultTreeAdapterMap> {
    constructor(...args: ConstructorParameters<typeof Parser<DefaultTreeAdapterMap>>) {
        super(...args)
        const tokenizer = this.tokenizer as unknown as {
            currentToken: { attrs: unknown[] } | null
            _leaveAttrName: () => void
        }
        const leaveAttrName = tokenizer._leaveAttrName.bind(tokenizer)
        tokenizer._leaveAttrName = () => {
            if ((tokenizer.currentToken?.attrs.length ?? 0) >= MAX_ATTRIBUTES_PER_TAG) {
                throw new Error(
                    'The sandbox email template could not retain its identification footer. Update the template and try again.'
                )
            }
            leaveAttrName()
        }
    }
}

const templateOwners = new WeakMap<DefaultTreeAdapterMap['parentNode'], DefaultTreeAdapterMap['template']>()

function refuseDeepNesting(parent: DefaultTreeAdapterMap['parentNode']): void {
    let depth = 0
    let current: DefaultTreeAdapterMap['parentNode'] | null | undefined = parent
    while (current) {
        depth += 1
        if (depth > MAX_ELEMENT_DEPTH) {
            throw new Error(
                'The sandbox email template could not retain its identification footer. Update the template and try again.'
            )
        }
        current = 'parentNode' in current ? current.parentNode : templateOwners.get(current)
    }
}

const depthBoundedTreeAdapter: TreeAdapter<DefaultTreeAdapterMap> = {
    ...defaultTreeAdapter,
    appendChild(parent, node) {
        refuseDeepNesting(parent)
        defaultTreeAdapter.appendChild(parent, node)
    },
    insertBefore(parent, node, reference) {
        refuseDeepNesting(parent)
        defaultTreeAdapter.insertBefore(parent, node, reference)
    },
    setTemplateContent(template, content) {
        templateOwners.set(content, template)
        defaultTreeAdapter.setTemplateContent(template, content)
    },
}

function parseBounded(html: string, scriptingEnabled = false): DefaultTreeAdapterMap['document'] {
    return AttributeBoundedParser.parse(html, { scriptingEnabled, treeAdapter: depthBoundedTreeAdapter })
}

class TooLargeForSandbox extends Error {
    constructor() {
        super(
            'Sandbox emails can have at most 75 KB of HTML, so every inbox shows the identification footer. Shorten the template and try again.'
        )
    }
}

function conditionalMarker(comment: string): ConditionalMarker | null {
    const data = comment.trim()
    const hidden = /^\[if\b([^\]]*)\]>([\s\S]*)<!\[endif\]$/i.exec(data)
    if (hidden) {
        if (/\[(?:if\b|endif\])/i.test(hidden[2])) {
            throw new UnreadableConditional()
        }
        return { kind: 'hidden', condition: hidden[1], content: hidden[2] }
    }
    const open = /^\[if\b([^\]]*)\](?:><!(?:--)?)?$/i.exec(data)
    if (open) {
        return { kind: 'open', condition: open[1] }
    }
    if (/^(?:<!)?\[endif\]$/i.test(data)) {
        return { kind: 'close' }
    }
    if (/\[(?:if\b|endif\])/i.test(data)) {
        throw new UnreadableConditional()
    }
    return null
}

function outlookViews(html: string): DefaultTreeAdapterMap['document'][] {
    const document = parseBounded(html)
    const marker = `outlook-conditional-${randomUUID()}-`
    const markers: ConditionalMarker[] = []
    const parents: DefaultTreeAdapterMap['parentNode'][] = [document]
    while (parents.length) {
        const parent = parents.pop()!
        const children =
            defaultTreeAdapter.isElementNode(parent) &&
            parent.tagName === 'template' &&
            parent.namespaceURI === htmlSpec.NS.HTML
                ? defaultTreeAdapter.getTemplateContent(parent as DefaultTreeAdapterMap['template'])
                : parent
        for (const node of [...children.childNodes]) {
            if (defaultTreeAdapter.isCommentNode(node)) {
                const found = conditionalMarker(node.data)
                if (found) {
                    defaultTreeAdapter.insertTextBefore(children, `${marker}${markers.length}-end`, node)
                    defaultTreeAdapter.detachNode(node)
                    markers.push(found)
                }
            } else if (defaultTreeAdapter.isElementNode(node)) {
                parents.push(node)
            }
        }
    }
    const marked = serialize(document, { scriptingEnabled: false })
    const pieces = marked.split(new RegExp(`${marker}(\\d+)-end`))
    const views = new Set<string>()
    for (const client of CONDITIONAL_CLIENTS) {
        let view = pieces[0]
        let skipping = false
        for (let index = 1; index < pieces.length; index += 2) {
            const found = markers[Number(pieces[index])]
            if (found.kind === 'close') {
                skipping = false
            } else if (skipping) {
                continue
            } else if (found.kind === 'open') {
                skipping = !conditionHolds(found.condition, client)
            } else if (conditionHolds(found.condition, client)) {
                view += found.content
            }
            view += skipping ? '' : pieces[index + 1]
        }
        views.add(view)
    }
    return [...views].map((view) => parseBounded(view))
}

function appendHtmlFooter(html: string, footer: string, preheader?: string): string {
    if (Buffer.byteLength(html) + Buffer.byteLength(preheader ?? '') > MAX_TEMPLATE_HTML_BYTES) {
        throw new TooLargeForSandbox()
    }
    const preheaderParser = AttributeBoundedParser.getFragmentParser(null, {
        scriptingEnabled: false,
        treeAdapter: depthBoundedTreeAdapter,
    })
    preheaderParser.tokenizer.write(preheader ?? '', true)
    const preheaderText = preheaderParser.getFragment()
    neutralizeRawTextElements(preheaderText.childNodes)
    const document = parseBounded(maybeAddPreheaderToEmail(html, serialize(preheaderText, { scriptingEnabled: false })))
    const body = htmlBody(document)
    if (!body) {
        throw new Error('The sandbox email template must have an HTML body. Update the template and try again.')
    }
    neutralizeRawTextElements(document.childNodes)
    protectFooterAncestors(document, body)
    const paragraph = defaultTreeAdapter.createElement('div', body.namespaceURI, [
        {
            name: 'style',
            value: 'all:initial!important;display:block!important;visibility:visible!important;opacity:1!important;position:relative!important;z-index:2147483647!important;inset:auto!important;float:none!important;width:auto!important;max-width:none!important;min-width:0!important;height:auto!important;max-height:none!important;overflow:visible!important;margin:0!important;transform:none!important;translate:none!important;scale:none!important;rotate:none!important;clip-path:none!important;filter:none!important;mask:none!important;-webkit-mask:none!important;mix-blend-mode:normal!important;text-indent:0!important;letter-spacing:normal!important;word-spacing:normal!important;text-transform:none!important;text-shadow:none!important;white-space:normal!important;font:12px sans-serif!important;color:#525252!important;background:#fff!important;padding:16px 0!important;mso-hide:none!important',
        },
    ])
    defaultTreeAdapter.insertText(paragraph, footer)
    defaultTreeAdapter.appendChild(body, paragraph)
    const serialized = serialize(document, { scriptingEnabled: false })
    if (Buffer.byteLength(serialized) > MAX_TEMPLATE_HTML_BYTES) {
        throw new TooLargeForSandbox()
    }
    if (leavesOutlookConditionalOpen(document.childNodes)) {
        throw new Error(
            'The sandbox email template could not retain its identification footer. Update the template and try again.'
        )
    }
    let conditionalRenderings: DefaultTreeAdapterMap['document'][]
    try {
        conditionalRenderings = outlookViews(serialized)
    } catch (error) {
        if (error instanceof UnreadableConditional) {
            throw new Error(
                'The sandbox email template could not retain its identification footer. Update the template and try again.'
            )
        }
        throw error
    }
    const renderings = [parseBounded(serialized), parseBounded(serialized, true), ...conditionalRenderings]
    for (const rendering of renderings) {
        const deliveredFooter = htmlBody(rendering)?.childNodes.at(-1)
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
