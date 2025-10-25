import { format } from 'util'

import { Webhook } from '@posthog/plugin-scaffold'

import { PostIngestionEvent, Team } from '../../types'
import { getPropertyValueByPath, stringify } from '../../utils/utils'

enum WebhookType {
    Slack = 'slack',
    Other = 'other',
}

// Sync with .../api/person.py and .../lib/constants.tsx
const PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES = [
    'email',
    'Email',
    '$email',
    'name',
    'Name',
    'username',
    'Username',
    'UserName',
]

const TOKENS_REGEX_BRACKETS_EXCLUDED = /(?<=(?<!\\)\[)(.*?)(?=(?<!\\)\])/g
const TOKENS_REGEX_BRACKETS_INCLUDED = /(?<!\\)\[(.*?)(?<!\\)\]/g

const determineWebhookType = (url: string): WebhookType => {
    url = url.toLowerCase()
    if (url.includes('slack.com')) {
        return WebhookType.Slack
    }
    return WebhookType.Other
}

export type WebhookFormatterOptions = {
    webhookUrl: string
    messageFormat: string
    event: PostIngestionEvent
    team: Team
    siteUrl: string
    sourcePath: string
    sourceName: string
}

export class WebhookFormatter {
    private webhookType: WebhookType
    private projectUrl: string
    private personLink: string
    private eventLink: string
    private sourceLink: string

    constructor(private options: WebhookFormatterOptions) {
        this.webhookType = determineWebhookType(options.webhookUrl)
        this.projectUrl = `${options.siteUrl}/project/${options.team.id}`

        this.personLink = `${this.projectUrl}/person/${encodeURIComponent(options.event.distinctId)}`
        this.eventLink = `${this.projectUrl}/events/${encodeURIComponent(options.event.eventUuid)}/${encodeURIComponent(
            options.event.timestamp
        )}`

        this.sourceLink = `${this.projectUrl}${options.sourcePath}`
    }

    composeWebhook(): Webhook {
        return {
            url: this.options.webhookUrl,
            body: JSON.stringify(this.generateWebhookPayload()),
            headers: {
                'Content-Type': 'application/json',
            },
            method: 'POST',
        }
    }

    generateWebhookPayload(): Record<string, any> {
        const [messageText, messageMarkdown] = this.getFormattedMessage()
        if (this.webhookType === WebhookType.Slack) {
            return {
                text: messageText,
                blocks: [{ type: 'section', text: { type: 'mrkdwn', text: messageMarkdown } }],
            }
        }
        return {
            text: messageMarkdown,
        }
    }

    private getFormattedMessage(): [string, string] {
        let messageText: string
        let messageMarkdown: string

        try {
            const [tokens, tokenizedMessage] = this.getTokens()
            const values: string[] = []
            const markdownValues: string[] = []

            for (const token of tokens) {
                const tokenParts = token.split('.') || []

                const [value, markdownValue] = this.getValueOfToken(tokenParts)
                values.push(value)
                markdownValues.push(markdownValue)
            }
            messageText = format(tokenizedMessage, ...values)
            messageMarkdown = format(tokenizedMessage, ...markdownValues)
        } catch (error) {
            const [sourceName, sourceMarkdown] = this.getSourceDetails()
            messageText = `⚠ Error: There are one or more formatting errors in the message template for source "${sourceName}".`
            messageMarkdown = `*⚠ Error: There are one or more formatting errors in the message template for source "${sourceMarkdown}".*`
        }

        return [messageText, messageMarkdown]
    }

    // https://api.slack.com/reference/surfaces/formatting#escaping
    private escapeSlack(text: string): string {
        return text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    }

    private escapeMarkdown(text: string): string {
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

    private webhookEscape(text: string): string {
        if (this.webhookType === WebhookType.Slack) {
            return this.escapeSlack(stringify(text))
        }
        return this.escapeMarkdown(stringify(text))
    }

    private toWebhookLink(text: string | null, url: string): [string, string] {
        const name = stringify(text)
        if (this.webhookType === WebhookType.Slack) {
            return [this.escapeSlack(name), `<${this.escapeSlack(url)}|${this.escapeSlack(name)}>`]
        } else {
            return [this.escapeMarkdown(name), `[${this.escapeMarkdown(name)}](${this.escapeMarkdown(url)})`]
        }
    }

    private getPersonDetails(): [string, string] {
        // Sync the logic below with the frontend `asDisplay`
        const personDisplayNameProperties =
            this.options.team.person_display_name_properties ?? PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES
        const customPropertyKey = personDisplayNameProperties.find((x) => this.options.event.person_properties?.[x])
        const propertyIdentifier = customPropertyKey
            ? this.options.event.person_properties[customPropertyKey]
            : undefined

        const customIdentifier: string =
            typeof propertyIdentifier !== 'string' ? JSON.stringify(propertyIdentifier) : propertyIdentifier

        const display: string | undefined = (customIdentifier || this.options.event.distinctId)?.trim()

        return this.toWebhookLink(display, this.personLink)
    }

    private getSourceDetails(): [string, string] {
        return this.toWebhookLink(this.options.sourceName, this.sourceLink)
    }

    private getEventDetails(): [string, string] {
        return this.toWebhookLink(this.options.event.event, this.eventLink)
    }

    private getGroupLink(groupIndex: number, groupKey: string): string {
        return `${this.projectUrl}/groups/${groupIndex}/${encodeURIComponent(groupKey)}`
    }

    private getTokens(): [string[], string] {
        // This finds property value tokens, basically any string contained in square brackets
        // Examples: "[foo]" is matched in "bar [foo]", "[action.name]" is matched in "action [action.name]"
        // The backslash is used as an escape character - "\[foo\]" is not matched, allowing square brackets in messages
        const matchedTokens = this.options.messageFormat.match(TOKENS_REGEX_BRACKETS_EXCLUDED) || []
        // Replace the tokens with placeholders, and unescape leftover brackets
        const tokenizedMessage = this.options.messageFormat
            .replace(TOKENS_REGEX_BRACKETS_INCLUDED, '%s')
            .replace(/\\(\[|\])/g, '$1')
        return [matchedTokens, tokenizedMessage]
    }

    private getValueOfToken(tokenParts: string[]): [string, string] {
        let text = ''
        let markdown = ''

        if (tokenParts[0] === 'user') {
            // [user.name] and [user.foo] are DEPRECATED as they had odd mechanics
            // [person] OR [event.properties.bar] should be used instead
            if (tokenParts[1] === 'name') {
                ;[text, markdown] = this.getPersonDetails()
            } else {
                const propertyName = `$${tokenParts[1]}`
                const property = this.options.event.properties?.[propertyName]
                markdown = text = this.webhookEscape(property)
            }
        } else if (tokenParts[0] === 'person') {
            if (tokenParts.length === 1) {
                ;[text, markdown] = this.getPersonDetails()
            } else if (tokenParts[1] === 'link') {
                markdown = text = this.webhookEscape(this.personLink)
            } else if (tokenParts[1] === 'properties' && tokenParts.length > 2) {
                const property = this.options.event.person_properties
                    ? getPropertyValueByPath(this.options.event.person_properties, tokenParts.slice(2))
                    : undefined
                markdown = text = this.webhookEscape(property)
            }
        } else if (tokenParts[0] === 'action' || tokenParts[0] === 'source') {
            if (tokenParts[1] === 'name') {
                ;[text, markdown] = this.getSourceDetails()
            } else if (tokenParts[1] === 'link') {
                markdown = text = this.webhookEscape(this.sourceLink)
            }
        } else if (tokenParts[0] === 'event') {
            if (tokenParts.length === 1) {
                ;[text, markdown] = this.getEventDetails()
            } else if (tokenParts[1] === 'link') {
                markdown = text = this.webhookEscape(this.eventLink)
            } else if (tokenParts[1] === 'uuid') {
                markdown = text = this.webhookEscape(this.options.event.eventUuid)
            } else if (tokenParts[1] === 'name') {
                // deprecated
                markdown = text = this.webhookEscape(this.options.event.event)
            } else if (tokenParts[1] === 'event') {
                markdown = text = this.webhookEscape(this.options.event.event)
            } else if (tokenParts[1] === 'timestamp') {
                markdown = text = this.webhookEscape(this.options.event.timestamp)
            } else if (tokenParts[1] === 'distinct_id') {
                markdown = text = this.webhookEscape(this.options.event.distinctId)
            } else if (tokenParts[1] === 'properties' && tokenParts.length > 2) {
                const property = this.options.event.properties
                    ? getPropertyValueByPath(this.options.event.properties, tokenParts.slice(2))
                    : undefined
                markdown = text = this.webhookEscape(property)
            }
        } else if (tokenParts[0] === 'groups') {
            if (tokenParts.length === 1) {
                // Summarise groups as a list
                markdown = text = 'NOT SUPPORTED'
            } else if (tokenParts.length > 1) {
                const relatedGroup = this.options.event.groups?.[tokenParts[1]]

                if (!relatedGroup) {
                    // What to return if no matching group?
                    const message = `(event without '${tokenParts[1]}')`
                    return [message, message]
                }

                if (tokenParts.length === 2) {
                    // Return the group name
                    // NOTE: group type is not correct...
                    ;[text, markdown] = this.toWebhookLink(
                        relatedGroup.properties.name || relatedGroup.key,
                        this.getGroupLink(relatedGroup.index, relatedGroup.key)
                    )
                } else if (tokenParts[2] === 'link') {
                    markdown = text = this.webhookEscape(this.getGroupLink(relatedGroup.index, relatedGroup.key))
                } else if (tokenParts[2] === 'properties' && tokenParts.length > 3) {
                    const property = relatedGroup.properties
                        ? getPropertyValueByPath(relatedGroup.properties, tokenParts.slice(3))
                        : undefined
                    markdown = text = this.webhookEscape(property)
                }
            }
        } else {
            throw new Error()
        }
        return [text, markdown]
    }
}
