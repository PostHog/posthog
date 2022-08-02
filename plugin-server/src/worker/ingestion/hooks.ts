import { captureException } from '@sentry/node'
import { StatsD } from 'hot-shots'
import fetch from 'node-fetch'
import { format } from 'util'

import { Action, Hook, IngestionEvent, IngestionPersonData } from '../../types'
import { DB } from '../../utils/db/db'
import { stringify } from '../../utils/utils'
import { LazyPersonContainer } from './lazy-person-container'
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

export function getUserDetails(
    event: IngestionEvent,
    person: IngestionPersonData | undefined,
    siteUrl: string,
    webhookType: WebhookType
): [string, string] {
    if (!person) {
        return ['undefined', 'undefined']
    }
    const userName = stringify(
        person.properties?.email || person.properties?.name || person.properties?.username || event.distinctId
    )
    let userMarkdown: string
    if (webhookType === WebhookType.Slack) {
        userMarkdown = `<${siteUrl}/person/${event.distinctId}|${userName}>`
    } else {
        userMarkdown = `[${userName}](${siteUrl}/person/${event.distinctId})`
    }
    return [userName, userMarkdown]
}

export function getActionDetails(action: Action, siteUrl: string, webhookType: WebhookType): [string, string] {
    const actionName = stringify(action.name)
    let actionMarkdown: string
    if (webhookType === WebhookType.Slack) {
        actionMarkdown = `<${siteUrl}/action/${action.id}|${actionName}>`
    } else {
        actionMarkdown = `[${actionName}](${siteUrl}/action/${action.id})`
    }
    return [actionName, actionMarkdown]
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

export async function getValueOfToken(
    action: Action,
    event: IngestionEvent,
    personContainer: LazyPersonContainer,
    siteUrl: string,
    webhookType: WebhookType,
    tokenParts: string[]
): Promise<[string, string]> {
    let text = ''
    let markdown = ''

    if (tokenParts[0] === 'user') {
        // [user.name] and [user.foo] are DEPRECATED as they had odd mechanics
        // [person] OR [event.properties.bar] should be used instead
        if (tokenParts[1] === 'name') {
            const person = await personContainer.get()
            ;[text, markdown] = getUserDetails(event, person, siteUrl, webhookType)
        } else {
            const propertyName = `$${tokenParts[1]}`
            const property = event.properties?.[propertyName]
            text = stringify(property)
            markdown = text
        }
    } else if (tokenParts[0] === 'person') {
        const person = await personContainer.get()
        if (tokenParts.length === 1) {
            ;[text, markdown] = getUserDetails(event, person, siteUrl, webhookType)
        } else if (tokenParts[1] === 'properties' && tokenParts.length > 2) {
            const propertyName = tokenParts[2]
            const property = person?.properties?.[propertyName]
            text = stringify(property)
            markdown = text
        }
    } else if (tokenParts[0] === 'action') {
        if (tokenParts[1] === 'name') {
            ;[text, markdown] = getActionDetails(action, siteUrl, webhookType)
        }
    } else if (tokenParts[0] === 'event') {
        if (tokenParts[1] === 'name') {
            text = stringify(event.event)
        } else if (tokenParts[1] === 'distinct_id') {
            text = stringify(event.distinctId)
        } else if (tokenParts[1] === 'properties' && tokenParts.length > 2) {
            const propertyName = tokenParts[2]
            const property = event.properties?.[propertyName]
            text = stringify(property)
        }
        markdown = text
    } else {
        throw new Error()
    }
    return [text, markdown]
}

export async function getFormattedMessage(
    action: Action,
    event: IngestionEvent,
    personContainer: LazyPersonContainer,
    siteUrl: string,
    webhookType: WebhookType
): Promise<[string, string]> {
    const messageFormat = action.slack_message_format || '[action.name] was triggered by [person]'
    let messageText: string
    let messageMarkdown: string

    try {
        const [tokens, tokenizedMessage] = getTokens(messageFormat)
        const values: string[] = []
        const markdownValues: string[] = []

        for (const token of tokens) {
            const tokenParts = token.match(/\$\w+|\$\$\w+|\w+/g) || []

            const [value, markdownValue] = await getValueOfToken(
                action,
                event,
                personContainer,
                siteUrl,
                webhookType,
                tokenParts
            )
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

    public async findAndFireHooks(
        event: IngestionEvent,
        personContainer: LazyPersonContainer,
        actionMatches: Action[]
    ): Promise<void> {
        if (!actionMatches.length) {
            return
        }

        const team = await this.teamManager.fetchTeam(event.teamId)

        if (!team) {
            return
        }

        const webhookUrl = team.slack_incoming_webhook
        const organization = await this.organizationManager.fetchOrganization(team.organization_id)

        if (webhookUrl) {
            const webhookRequests = actionMatches
                .filter((action) => action.post_to_slack)
                .map((action) => this.postWebhook(webhookUrl, action, event, personContainer))
            await Promise.all(webhookRequests).catch((error) => captureException(error))
        }

        if (organization!.available_features.includes('zapier')) {
            const restHooks = actionMatches.map(({ hooks }) => hooks).flat()

            if (restHooks.length > 0) {
                const person = await personContainer.get()

                const restHookRequests = restHooks.map((hook) => this.postRestHook(hook, event, person))
                await Promise.all(restHookRequests).catch((error) => captureException(error))

                this.statsd?.increment('zapier_hooks_fired', {
                    team_id: String(team.id),
                })
            }
        }
    }

    private async postWebhook(
        webhookUrl: string,
        action: Action,
        event: IngestionEvent,
        personContainer: LazyPersonContainer
    ): Promise<void> {
        const webhookType = determineWebhookType(webhookUrl)
        const siteUrl = await this.siteUrlManager.getSiteUrl()
        const [messageText, messageMarkdown] = await getFormattedMessage(
            action,
            event,
            personContainer,
            siteUrl || '',
            webhookType
        )
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
        })
        this.statsd?.increment('webhook_firings', {
            team_id: event.teamId.toString(),
        })
    }

    public async postRestHook(
        hook: Hook,
        event: IngestionEvent,
        person: IngestionPersonData | undefined
    ): Promise<void> {
        let sendablePerson: Record<string, any> = {}
        if (person) {
            const { uuid, properties, team_id, id } = person

            // we standardize into ISO before sending the payload
            const createdAt = person.created_at.toISO()

            sendablePerson = {
                uuid,
                properties,
                team_id,
                id,
                created_at: createdAt,
            }
        }

        const payload = {
            hook: { id: hook.id, event: hook.event, target: hook.target },
            data: { ...event, person: sendablePerson },
        }
        const request = await fetch(hook.target, {
            method: 'POST',
            body: JSON.stringify(payload, undefined, 4),
            headers: { 'Content-Type': 'application/json' },
        })
        if (request.status === 410) {
            // Delete hook on our side if it's gone on Zapier's
            await this.db.deleteRestHook(hook.id)
        }
        this.statsd?.increment('rest_hook_firings')
    }
}
