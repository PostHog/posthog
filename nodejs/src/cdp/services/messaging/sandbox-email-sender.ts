import { type DefaultTreeAdapterMap, defaultTreeAdapter, parse, serialize } from 'parse5'

import { CyclotronInvocationQueueParametersEmailType } from '~/cdp/schema/cyclotron'
import { logger } from '~/common/utils/logger'
import { captureTeamEvent } from '~/common/utils/posthog'
import { TeamManager } from '~/common/utils/team-manager'

import { maybeAddPreheaderToEmail } from './helpers/preheader'

export interface SandboxEmailSenderConfig {
    enabled: boolean
    tenantName: string
    configurationSetName: string
    fromAddress: string
}

type SandboxEmailOutcome =
    | { type: 'sent'; recipientCount: number }
    | { type: 'blocked'; reason: 'switch_off'; blockedRecipientCount: number }

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
        private teamManager: TeamManager
    ) {}

    public async withIdentificationFooter(
        params: CyclotronInvocationQueueParametersEmailType,
        senderName: string,
        teamId: number
    ): Promise<CyclotronInvocationQueueParametersEmailType> {
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
