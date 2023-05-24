import { captureException } from '@sentry/node'
import { StatsD } from 'hot-shots'
import { format } from 'util'

import { Action, Hook, PostIngestionEvent } from '../../types'
import { DB } from '../../utils/db/db'
import fetch from '../../utils/fetch'
import { status } from '../../utils/status'
import { stringify } from '../../utils/utils'
import { OrganizationManager } from './organization-manager'
import { SiteUrlManager } from './site-url-manager'
import { TeamManager } from './team-manager'

export enum WebhookType {
    Slack = 'slack',
    Discord = 'discord',
    Teams = 'teams',
}

export function determineWebhookType(url: string): WebhookType {
    url = url.toLowerCase()
    if (url.includes('slack.com')) {
        return WebhookType.Slack
    }
    if (url.includes('discord.com')) {
        return WebhookType.Discord
    }
    return WebhookType.Teams
}

export function toWebhookLink(text: string | null, url: string, webhookType: WebhookType): [string, string] {
    const name = stringify(text)
    let markdown: string
    if (webhookType === WebhookType.Slack) {
        markdown = `<${url}|${name}>`
    } else {
        markdown = `[${name}](${url})`
    }
    return [name, markdown]
}

export function getUserDetails(event: PostIngestionEvent, siteUrl: string, webhookType: WebhookType): [string, string] {
    const userName =
        event.person_properties?.email ||
        event.person_properties?.name ||
        event.person_properties?.username ||
        event.distinctId
    return toWebhookLink(userName, `${siteUrl}/person/${event.distinctId}`, webhookType)
}

export function getActionDetails(action: Action, siteUrl: string, webhookType: WebhookType): [string, string] {
    return toWebhookLink(action.name, `${siteUrl}/action/${action.id}`, webhookType)
}

export function getEventDetails(
    event: PostIngestionEvent,
    siteUrl: string,
    webhookType: WebhookType
): [string, string] {
    return toWebhookLink(event.event, `${siteUrl}/events/${event.eventUuid}`, webhookType)
}

export function getTokens(messageFormat: string): [string[], string] {
    // This finds property value tokens, basically any string contained in square brackets
    // Examples: "[foo]" is matched in "bar [foo]", "[action.name]" is matched in "action [action.name]"
    const TOKENS_REGEX = /(?<=\[)(.*?)(?=\])/g
    const matchedTokens = messageFormat.match(TOKENS_REGEX) || []
    let tokenizedMessage = messageFormat
    if (matchedTokens.length) {
        tokenizedMessage = tokenizedMessage.replace(/\[(.*?)\]/g, '%s')
    }
    return [matchedTokens, tokenizedMessage]
}

export function getValueOfToken(
    action: Action,
    event: PostIngestionEvent,
    siteUrl: string,
    webhookType: WebhookType,
    tokenParts: string[]
): [string, string] {
    let text = ''
    let markdown = ''

    if (tokenParts[0] === 'user') {
        // [user.name] and [user.foo] are DEPRECATED as they had odd mechanics
        // [person] OR [event.properties.bar] should be used instead
        if (tokenParts[1] === 'name') {
            ;[text, markdown] = getUserDetails(event, siteUrl, webhookType)
        } else {
            const propertyName = `$${tokenParts[1]}`
            const property = event.properties?.[propertyName]
            text = stringify(property)
            markdown = text
        }
    } else if (tokenParts[0] === 'person') {
        if (tokenParts.length === 1) {
            ;[text, markdown] = getUserDetails(event, siteUrl, webhookType)
        } else if (tokenParts[1] === 'properties' && tokenParts.length > 2) {
            const propertyName = tokenParts[2]
            const property = event.person_properties?.[propertyName]
            text = stringify(property)
            markdown = text
        }
    } else if (tokenParts[0] === 'action') {
        if (tokenParts[1] === 'name') {
            ;[text, markdown] = getActionDetails(action, siteUrl, webhookType)
        }
    } else if (tokenParts[0] === 'event') {
        if (tokenParts[1] === 'uuid') {
            text = stringify(event.eventUuid)
            markdown = text
        } else if (tokenParts[1] === 'name') {
            text = stringify(event.event)
            markdown = text
        } else if (tokenParts[1] === 'event') {
            ;[text, markdown] = getEventDetails(event, siteUrl, webhookType)
        } else if (tokenParts[1] === 'distinct_id') {
            text = stringify(event.distinctId)
            markdown = text
        } else if (tokenParts[1] === 'properties' && tokenParts.length > 2) {
            const propertyName = tokenParts[2]
            const property = event.properties?.[propertyName]
            text = stringify(property)
            markdown = text
        }
    } else {
        throw new Error()
    }
    return [text, markdown]
}

export function getFormattedMessage(
    action: Action,
    event: PostIngestionEvent,
    siteUrl: string,
    webhookType: WebhookType
): [string, string] {
    const messageFormat = action.slack_message_format || '[action.name] was triggered by [person]'
    let messageText: string
    let messageMarkdown: string

    try {
        const [tokens, tokenizedMessage] = getTokens(messageFormat)
        const values: string[] = []
        const markdownValues: string[] = []

        for (const token of tokens) {
            const tokenParts = token.match(/\$\w+|\$\$\w+|\w+/g) || []

            const [value, markdownValue] = getValueOfToken(action, event, siteUrl, webhookType, tokenParts)
            values.push(value)
            markdownValues.push(markdownValue)
        }
        messageText = format(tokenizedMessage, ...values)
        messageMarkdown = format(tokenizedMessage, ...markdownValues)
    } catch (error) {
        const [actionName, actionMarkdown] = getActionDetails(action, siteUrl, webhookType)
        messageText = `⚠ Error: There are one or more formatting errors in the message template for action "${actionName}".`
        messageMarkdown = `*⚠ Error: There are one or more formatting errors in the message template for action "${actionMarkdown}".*`
    }

    return [messageText, messageMarkdown]
}

export class HookCommander {
    db: DB
    teamManager: TeamManager
    organizationManager: OrganizationManager
    siteUrlManager: SiteUrlManager
    statsd: StatsD | undefined

    /** Hook request timeout in ms. */
    EXTERNAL_REQUEST_TIMEOUT = 10 * 1000

    constructor(
        db: DB,
        teamManager: TeamManager,
        organizationManager: OrganizationManager,
        siteUrlManager: SiteUrlManager,
        statsd?: StatsD
    ) {
        this.db = db
        this.teamManager = teamManager
        this.organizationManager = organizationManager
        this.siteUrlManager = siteUrlManager
        this.statsd = statsd
    }

    public async findAndFireHooks(event: PostIngestionEvent, actionMatches: Action[]): Promise<void> {
        status.debug('🔍', `Looking for hooks to fire for event "${event.event}"`)
        if (!actionMatches.length) {
            status.debug('🔍', `No hooks to fire for event "${event.event}"`)
            return
        }
        status.debug('🔍', `Found ${actionMatches.length} matching actions`)

        const team = await this.teamManager.fetchTeam(event.teamId)

        if (!team) {
            return
        }

        const webhookUrl = team.slack_incoming_webhook

        if (webhookUrl) {
            const webhookRequests = actionMatches
                .filter((action) => action.post_to_slack)
                .map((action) => this.postWebhook(webhookUrl, action, event))
            await Promise.all(webhookRequests).catch((error) =>
                captureException(error, { tags: { team_id: event.teamId } })
            )
        }

        if (await this.organizationManager.hasAvailableFeature(team.id, 'zapier')) {
            const restHooks = actionMatches.map(({ hooks }) => hooks).flat()

            if (restHooks.length > 0) {
                const restHookRequests = restHooks.map((hook) => this.postRestHook(hook, event))
                await Promise.all(restHookRequests).catch((error) =>
                    captureException(error, { tags: { team_id: event.teamId } })
                )

                this.statsd?.increment('zapier_hooks_fired', {
                    team_id: String(team.id),
                })
            }
        }
    }

    private async postWebhook(webhookUrl: string, action: Action, event: PostIngestionEvent): Promise<void> {
        const webhookType = determineWebhookType(webhookUrl)
        const siteUrl = await this.siteUrlManager.getSiteUrl()
        const [messageText, messageMarkdown] = getFormattedMessage(action, event, siteUrl || '', webhookType)
        let message: Record<string, any>
        if (webhookType === WebhookType.Slack) {
            message = {
                text: messageText,
                blocks: [{ type: 'section', text: { type: 'mrkdwn', text: messageMarkdown } }],
            }
        } else {
            message = {
                text: messageMarkdown,
            }
        }

        await fetch(webhookUrl, {
            method: 'POST',
            body: JSON.stringify(message, undefined, 4),
            headers: { 'Content-Type': 'application/json' },
            timeout: this.EXTERNAL_REQUEST_TIMEOUT,
        })
        this.statsd?.increment('webhook_firings', {
            team_id: event.teamId.toString(),
        })
    }

    public async postRestHook(hook: Hook, event: PostIngestionEvent): Promise<void> {
        let sendablePerson: Record<string, any> = {}
        const { person_id, person_created_at, person_properties, ...data } = event
        if (person_id) {
            sendablePerson = {
                uuid: person_id,
                properties: person_properties,
                created_at: person_created_at,
            }
        }

        const payload = {
            hook: { id: hook.id, event: hook.event, target: hook.target },
            data: { ...data, person: sendablePerson },
        }

        const request = await fetch(hook.target, {
            method: 'POST',
            body: JSON.stringify(payload, undefined, 4),
            headers: { 'Content-Type': 'application/json' },
            timeout: this.EXTERNAL_REQUEST_TIMEOUT,
        })
        if (request.status === 410) {
            // Delete hook on our side if it's gone on Zapier's
            await this.db.deleteRestHook(hook.id)
        }
        this.statsd?.increment('rest_hook_firings')
    }
}
