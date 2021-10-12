import { PluginEvent } from '@posthog/plugin-scaffold'
import { captureException } from '@sentry/node'
import { StatsD } from 'hot-shots'
import fetch from 'node-fetch'
import { format } from 'util'

import { Action, Hook, Person } from '../../types'
import { DB } from '../../utils/db/db'
import { stringify } from '../../utils/utils'
import { OrganizationManager } from './organization-manager'
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
    event: PluginEvent,
    person: Person | undefined,
    siteUrl: string,
    webhookType: WebhookType
): [string, string] {
    if (!person) {
        return ['undefined', 'undefined']
    }
    const userName = stringify(person.properties?.['email'] || event.distinct_id)
    let userMarkdown: string
    if (webhookType === WebhookType.Slack) {
        userMarkdown = `<${siteUrl}/person/${event.distinct_id}|${userName}>`
    } else {
        userMarkdown = `[${userName}](${siteUrl}/person/${event.distinct_id})`
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

export function getValueOfToken(
    action: Action,
    event: PluginEvent,
    person: Person | undefined,
    siteUrl: string,
    webhookType: WebhookType,
    tokenParts: string[]
): [string, string] {
    let text = ''
    let markdown = ''

    if (tokenParts[0] === 'user') {
        if (tokenParts[1] === 'name') {
            ;[text, markdown] = getUserDetails(event, person, siteUrl, webhookType)
        } else {
            const propertyName = `$${tokenParts[1]}`
            const property = event.properties?.[propertyName]
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

export function getFormattedMessage(
    action: Action,
    event: PluginEvent,
    person: Person | undefined,
    siteUrl: string,
    webhookType: WebhookType
): [string, string] {
    const messageFormat = action.slack_message_format || '[action.name] was triggered by [user.name]'
    let messageText: string
    let messageMarkdown: string

    try {
        const [tokens, tokenizedMessage] = getTokens(messageFormat)
        const values: string[] = []
        const markdownValues: string[] = []

        for (const token of tokens) {
            const tokenParts = token.match(/\w+/g) || []

            const [value, markdownValue] = getValueOfToken(action, event, person, siteUrl, webhookType, tokenParts)
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
    statsd: StatsD | undefined

    constructor(db: DB, teamManager: TeamManager, organizationManager: OrganizationManager, statsd?: StatsD) {
        this.db = db
        this.teamManager = teamManager
        this.organizationManager = organizationManager
        this.statsd = statsd
    }

    public async findAndFireHooks(
        event: PluginEvent,
        person: Person | undefined,
        siteUrl: string,
        actionMatches: Action[]
    ): Promise<void> {
        if (!actionMatches.length) {
            return
        }

        const team = await this.teamManager.fetchTeam(event.team_id)

        if (!team) {
            return
        }

        const webhookUrl = team.slack_incoming_webhook
        const organization = await this.organizationManager.fetchOrganization(team.organization_id)

        if (webhookUrl) {
            const webhookRequests = actionMatches
                .filter((action) => action.post_to_slack)
                .map((action) => this.postWebhook(webhookUrl, action, event, person, siteUrl))
            await Promise.all(webhookRequests).catch((error) => captureException(error))
        }

        if (organization!.available_features.includes('zapier')) {
            const restHooks = (
                await Promise.all(
                    actionMatches.map(
                        async (action) => await this.db.fetchRelevantRestHooks(team.id, 'action_performed', action.id)
                    )
                )
            ).flat()
            const restHookRequests = restHooks.map((hook) => this.postRestHook(hook, event, person))
            await Promise.all(restHookRequests).catch((error) => captureException(error))
        }
    }

    private async postWebhook(
        webhookUrl: string,
        action: Action,
        event: PluginEvent,
        person: Person | undefined,
        siteUrl: string
    ): Promise<void> {
        const webhookType = determineWebhookType(webhookUrl)
        const [messageText, messageMarkdown] = getFormattedMessage(action, event, person, siteUrl, webhookType)
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
        this.statsd?.increment('webhook_firings')
    }

    private async postRestHook(hook: Hook, event: PluginEvent, person: Person | undefined): Promise<void> {
        const payload = {
            hook: { id: hook.id, event: hook.event, target: hook.target },
            data: { ...event, person },
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
