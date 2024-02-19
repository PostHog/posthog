import { captureException } from '@sentry/node'
import { Histogram } from 'prom-client'
import { format } from 'util'
import { RustyHook } from 'worker/rusty-hook'

import { Action, Hook, PostIngestionEvent, Team } from '../../types'
import { PostgresRouter, PostgresUse } from '../../utils/db/postgres'
import { trackedFetch } from '../../utils/fetch'
import { status } from '../../utils/status'
import { getPropertyValueByPath, stringify } from '../../utils/utils'
import { AppMetric, AppMetrics } from './app-metrics'
import { OrganizationManager } from './organization-manager'
import { TeamManager } from './team-manager'

export const webhookProcessStepDuration = new Histogram({
    name: 'webhook_process_event_duration',
    help: 'Processing step latency to during webhooks processing, per tag',
    labelNames: ['tag'],
})

export async function instrumentWebhookStep<T>(tag: string, run: () => Promise<T>): Promise<T> {
    const end = webhookProcessStepDuration
        .labels({
            tag: tag,
        })
        .startTimer()
    const res = await run()
    end()
    return res
}

export enum WebhookType {
    Slack = 'slack',
    Discord = 'discord',
    Other = 'other',
}

export function determineWebhookType(url: string): WebhookType {
    url = url.toLowerCase()
    if (url.includes('slack.com')) {
        return WebhookType.Slack
    }
    if (url.includes('discord.com')) {
        return WebhookType.Discord
    }
    return WebhookType.Other
}

// https://api.slack.com/reference/surfaces/formatting#escaping
function escapeSlack(text: string): string {
    return text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
}

function escapeMarkdown(text: string): string {
    const markdownChars: string[] = ['\\', '`', '*', '_', '{', '}', '[', ']', '(', ')', '!']
    const lineStartChars: string[] = ['#', '-', '+']

    let escapedText = ''
    let isNewLine = true

    for (const char of text) {
        if (isNewLine && lineStartChars.includes(char)) {
            escapedText += '\\' + char
        } else if (!isNewLine && markdownChars.includes(char)) {
            escapedText += '\\' + char
        } else {
            escapedText += char
        }

        isNewLine = char === '\n' || char === '\r'
    }

    return escapedText
}

export function webhookEscape(text: string, webhookType: WebhookType): string {
    if (webhookType === WebhookType.Slack) {
        return escapeSlack(stringify(text))
    }
    return escapeMarkdown(stringify(text))
}

export function toWebhookLink(text: string | null, url: string, webhookType: WebhookType): [string, string] {
    const name = stringify(text)
    if (webhookType === WebhookType.Slack) {
        return [escapeSlack(name), `<${escapeSlack(url)}|${escapeSlack(name)}>`]
    } else {
        return [escapeMarkdown(name), `[${escapeMarkdown(name)}](${escapeMarkdown(url)})`]
    }
}

// Sync with .../api/person.py and .../lib/constants.tsx
export const PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES = [
    'email',
    'Email',
    'name',
    'Name',
    'username',
    'Username',
    'UserName',
]

export function getPersonLink(event: PostIngestionEvent, siteUrl: string): string {
    return `${siteUrl}/person/${encodeURIComponent(event.distinctId)}`
}
export function getPersonDetails(
    event: PostIngestionEvent,
    siteUrl: string,
    webhookType: WebhookType,
    team: Team
): [string, string] {
    // Sync the logic below with the frontend `asDisplay`
    const personDisplayNameProperties = team.person_display_name_properties ?? PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES
    const customPropertyKey = personDisplayNameProperties.find((x) => event.person_properties?.[x])
    const propertyIdentifier = customPropertyKey ? event.person_properties[customPropertyKey] : undefined

    const customIdentifier: string =
        typeof propertyIdentifier !== 'string' ? JSON.stringify(propertyIdentifier) : propertyIdentifier

    const display: string | undefined = (customIdentifier || event.distinctId)?.trim()

    return toWebhookLink(display, getPersonLink(event, siteUrl), webhookType)
}

export function getActionLink(action: Action, siteUrl: string): string {
    return `${siteUrl}/action/${action.id}`
}
export function getActionDetails(action: Action, siteUrl: string, webhookType: WebhookType): [string, string] {
    return toWebhookLink(action.name, getActionLink(action, siteUrl), webhookType)
}

export function getEventLink(event: PostIngestionEvent, siteUrl: string): string {
    return `${siteUrl}/events/${encodeURIComponent(event.eventUuid)}/${encodeURIComponent(event.timestamp)}`
}
export function getEventDetails(
    event: PostIngestionEvent,
    siteUrl: string,
    webhookType: WebhookType
): [string, string] {
    return toWebhookLink(event.event, getEventLink(event, siteUrl), webhookType)
}

const TOKENS_REGEX_BRACKETS_EXCLUDED = /(?<=(?<!\\)\[)(.*?)(?=(?<!\\)\])/g
const TOKENS_REGEX_BRACKETS_INCLUDED = /(?<!\\)\[(.*?)(?<!\\)\]/g

export function getTokens(messageFormat: string): [string[], string] {
    // This finds property value tokens, basically any string contained in square brackets
    // Examples: "[foo]" is matched in "bar [foo]", "[action.name]" is matched in "action [action.name]"
    // The backslash is used as an escape character - "\[foo\]" is not matched, allowing square brackets in messages
    const matchedTokens = messageFormat.match(TOKENS_REGEX_BRACKETS_EXCLUDED) || []
    // Replace the tokens with placeholders, and unescape leftover brackets
    const tokenizedMessage = messageFormat.replace(TOKENS_REGEX_BRACKETS_INCLUDED, '%s').replace(/\\(\[|\])/g, '$1')
    return [matchedTokens, tokenizedMessage]
}

export function getValueOfToken(
    action: Action,
    event: PostIngestionEvent,
    team: Team,
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
            ;[text, markdown] = getPersonDetails(event, siteUrl, webhookType, team)
        } else {
            const propertyName = `$${tokenParts[1]}`
            const property = event.properties?.[propertyName]
            markdown = text = webhookEscape(property, webhookType)
        }
    } else if (tokenParts[0] === 'person') {
        if (tokenParts.length === 1) {
            ;[text, markdown] = getPersonDetails(event, siteUrl, webhookType, team)
        } else if (tokenParts[1] === 'link') {
            markdown = text = webhookEscape(getPersonLink(event, siteUrl), webhookType)
        } else if (tokenParts[1] === 'properties' && tokenParts.length > 2) {
            const property = event.person_properties
                ? getPropertyValueByPath(event.person_properties, tokenParts.slice(2))
                : undefined
            markdown = text = webhookEscape(property, webhookType)
        }
    } else if (tokenParts[0] === 'action') {
        if (tokenParts[1] === 'name') {
            ;[text, markdown] = getActionDetails(action, siteUrl, webhookType)
        } else if (tokenParts[1] === 'link') {
            markdown = text = webhookEscape(getActionLink(action, siteUrl), webhookType)
        }
    } else if (tokenParts[0] === 'event') {
        if (tokenParts.length === 1) {
            ;[text, markdown] = getEventDetails(event, siteUrl, webhookType)
        } else if (tokenParts[1] === 'link') {
            markdown = text = webhookEscape(getEventLink(event, siteUrl), webhookType)
        } else if (tokenParts[1] === 'uuid') {
            markdown = text = webhookEscape(event.eventUuid, webhookType)
        } else if (tokenParts[1] === 'name') {
            // deprecated
            markdown = text = webhookEscape(event.event, webhookType)
        } else if (tokenParts[1] === 'event') {
            markdown = text = webhookEscape(event.event, webhookType)
        } else if (tokenParts[1] === 'distinct_id') {
            markdown = text = webhookEscape(event.distinctId, webhookType)
        } else if (tokenParts[1] === 'properties' && tokenParts.length > 2) {
            const property = event.properties
                ? getPropertyValueByPath(event.properties, tokenParts.slice(2))
                : undefined
            markdown = text = webhookEscape(property, webhookType)
        }
    } else {
        throw new Error()
    }
    return [text, markdown]
}

export function getFormattedMessage(
    messageFormat: string,
    action: Action,
    event: PostIngestionEvent,
    team: Team,
    siteUrl: string,
    webhookType: WebhookType
): [string, string] {
    let messageText: string
    let messageMarkdown: string

    try {
        const [tokens, tokenizedMessage] = getTokens(messageFormat)
        const values: string[] = []
        const markdownValues: string[] = []

        for (const token of tokens) {
            const tokenParts = token.split('.') || []

            const [value, markdownValue] = getValueOfToken(action, event, team, siteUrl, webhookType, tokenParts)
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
    postgres: PostgresRouter
    teamManager: TeamManager
    organizationManager: OrganizationManager
    rustyHook: RustyHook
    appMetrics: AppMetrics
    siteUrl: string
    /** Hook request timeout in ms. */
    EXTERNAL_REQUEST_TIMEOUT: number

    constructor(
        postgres: PostgresRouter,
        teamManager: TeamManager,
        organizationManager: OrganizationManager,
        rustyHook: RustyHook,
        appMetrics: AppMetrics,
        timeout: number
    ) {
        this.postgres = postgres
        this.teamManager = teamManager
        this.organizationManager = organizationManager
        if (process.env.SITE_URL) {
            this.siteUrl = process.env.SITE_URL
        } else {
            status.warn('⚠️', 'SITE_URL env is not set for webhooks')
            this.siteUrl = ''
        }
        this.rustyHook = rustyHook
        this.appMetrics = appMetrics
        this.EXTERNAL_REQUEST_TIMEOUT = timeout
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
            await instrumentWebhookStep('postWebhook', async () => {
                const webhookRequests = actionMatches
                    .filter((action) => action.post_to_slack)
                    .map((action) => this.postWebhook(event, action, team))
                await Promise.all(webhookRequests).catch((error) =>
                    captureException(error, { tags: { team_id: event.teamId } })
                )
            })
        }

        if (await this.organizationManager.hasAvailableFeature(team.id, 'zapier')) {
            await instrumentWebhookStep('postRestHook', async () => {
                const restHooks = actionMatches.flatMap((action) => action.hooks.map((hook) => ({ hook, action })))

                if (restHooks.length > 0) {
                    const restHookRequests = restHooks.map(({ hook, action }) =>
                        this.postWebhook(event, action, team, hook)
                    )
                    await Promise.all(restHookRequests).catch((error) =>
                        captureException(error, { tags: { team_id: event.teamId } })
                    )
                }
            })
        }
    }

    private formatMessage(
        webhookUrl: string,
        messageFormat: string,
        action: Action,
        event: PostIngestionEvent,
        team: Team
    ): Record<string, any> {
        const endTimer = webhookProcessStepDuration.labels('messageFormatting').startTimer()
        try {
            const webhookType = determineWebhookType(webhookUrl)
            const [messageText, messageMarkdown] = getFormattedMessage(
                messageFormat,
                action,
                event,
                team,
                this.siteUrl,
                webhookType
            )
            if (webhookType === WebhookType.Slack) {
                return {
                    text: messageText,
                    blocks: [{ type: 'section', text: { type: 'mrkdwn', text: messageMarkdown } }],
                }
            }
            return {
                text: messageMarkdown,
            }
        } finally {
            endTimer()
        }
    }

    public async postWebhook(event: PostIngestionEvent, action: Action, team: Team, hook?: Hook): Promise<void> {
        // Used if no hook is provided
        const defaultWebhookUrl = team.slack_incoming_webhook
        // -2 is hardcoded to mean webhooks, -1 for resthooks
        const SPECIAL_CONFIG_ID = hook ? -1 : -2
        const partialMetric: AppMetric = {
            teamId: event.teamId,
            pluginConfigId: SPECIAL_CONFIG_ID,
            category: 'webhook',
            successes: 1,
        }

        const url = hook ? hook.target : defaultWebhookUrl
        let body: any

        if (!url) {
            // NOTE: Typically this is covered by the caller already
            return
        }

        if (!hook) {
            const messageFormat = action.slack_message_format || '[action.name] was triggered by [person]'
            body = this.formatMessage(url, messageFormat, action, event, team)
        } else if (hook.format_text) {
            body = this.formatMessage(url, hook.format_text, action, event, team)
        } else {
            let sendablePerson: Record<string, any> = {}
            const { person_id, person_created_at, person_properties, ...data } = event
            if (person_id) {
                sendablePerson = {
                    uuid: person_id,
                    properties: person_properties,
                    created_at: person_created_at,
                }
            }

            body = {
                hook: { id: hook.id, event: hook.event, target: hook.target },
                data: { ...data, person: sendablePerson },
            }
        }

        const enqueuedInRustyHook = await this.rustyHook.enqueueIfEnabledForTeam({
            webhook: {
                url,
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body, undefined, 4),
            },
            teamId: event.teamId,
            pluginId: SPECIAL_CONFIG_ID,
            pluginConfigId: SPECIAL_CONFIG_ID, // -2 is hardcoded to mean webhooks
        })

        if (enqueuedInRustyHook) {
            // Rusty-Hook handles it from here, so we're done.
            return
        }

        const slowWarningTimeout = this.EXTERNAL_REQUEST_TIMEOUT * 0.7
        const timeout = setTimeout(() => {
            status.warn(
                '⌛',
                `Posting Webhook slow. Timeout warning after ${slowWarningTimeout / 1000} sec! url=${url} team_id=${
                    team.id
                } event_id=${event.eventUuid}`
            )
        }, slowWarningTimeout)

        status.debug('⚠️', `Firing webhook ${url} for team ${team.id}`)

        try {
            await instrumentWebhookStep('fetch', async () => {
                const request = await trackedFetch(url, {
                    method: 'POST',
                    body: JSON.stringify(body, null, 2),
                    headers: { 'Content-Type': 'application/json' },
                    timeout: this.EXTERNAL_REQUEST_TIMEOUT,
                })
                // special handling for hooks
                if (hook && request.status === 410) {
                    // Delete hook on our side if it's gone on Zapier's
                    await this.deleteRestHook(hook.id)
                }
                if (!request.ok) {
                    status.warn('⚠️', `HTTP status ${request.status} for team ${team.id}`)
                    await this.appMetrics.queueError(
                        {
                            ...partialMetric,
                            failures: 1,
                        },
                        {
                            error: `Request failed with HTTP status ${request.status}`,
                            event,
                        }
                    )
                } else {
                    await this.appMetrics.queueMetric({
                        ...partialMetric,
                        successes: 1,
                    })
                }
            })
        } catch (error) {
            await this.appMetrics.queueError(
                {
                    ...partialMetric,
                    failures: 1,
                },
                {
                    error,
                    event,
                }
            )
            throw error
        } finally {
            clearTimeout(timeout)
        }
    }

    private async deleteRestHook(hookId: Hook['id']): Promise<void> {
        await this.postgres.query(
            PostgresUse.COMMON_WRITE,
            `DELETE FROM ee_hook WHERE id = $1`,
            [hookId],
            'deleteRestHook'
        )
    }
}
