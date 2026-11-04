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
import { logger } from '~/common/utils/logger'
import { TeamManager } from '~/common/utils/team-manager'

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

export class SandboxEmailSender {
    public readonly canSend: boolean

    constructor(
        public readonly config: SandboxEmailSenderConfig,
        private teamManager: TeamManager
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
}
