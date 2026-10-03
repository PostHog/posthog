import { defaultTreeAdapter, parse, serialize } from 'parse5'

import { CyclotronInvocationQueueParametersEmailType } from '~/cdp/schema/cyclotron'
import { logger } from '~/common/utils/logger'
import { captureTeamEvent } from '~/common/utils/posthog'
import { TeamManager } from '~/common/utils/team-manager'

export interface SandboxEmailSenderConfig {
    enabled: boolean
    tenantName: string
    configurationSetName: string
    fromAddress: string
}

type SandboxEmailOutcome =
    | { type: 'sent'; recipientCount: number }
    | { type: 'blocked'; reason: 'switch_off'; blockedRecipientCount: number }

function appendHtmlFooter(html: string, footer: string): string {
    const document = parse(html)
    const root = document.childNodes.find(defaultTreeAdapter.isElementNode)
    const body = root?.childNodes.find((node) => defaultTreeAdapter.isElementNode(node) && node.tagName === 'body')
    if (!body || !defaultTreeAdapter.isElementNode(body)) {
        throw new Error('The sandbox email template must have an HTML body. Update the template and try again.')
    }
    const nodes = [...body.childNodes]
    for (const node of nodes) {
        if (defaultTreeAdapter.isElementNode(node)) {
            if (node.tagName === 'plaintext') {
                node.tagName = 'pre'
            }
            nodes.push(...node.childNodes)
        }
    }
    const paragraph = defaultTreeAdapter.createElement('div', body.namespaceURI, [
        {
            name: 'style',
            value: 'all:initial!important;display:block!important;visibility:visible!important;opacity:1!important;font:12px sans-serif!important;color:#525252!important;padding:16px 0!important',
        },
    ])
    defaultTreeAdapter.insertText(paragraph, footer)
    defaultTreeAdapter.appendChild(body, paragraph)
    return serialize(document)
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
            ...(params.text ? { text: `${params.text}\n\n${footer}` } : {}),
            ...(params.html ? { html: appendHtmlFooter(params.html, footer) } : {}),
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
