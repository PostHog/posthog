import { format } from 'util'

import { PostIngestionEvent, Team } from '../../types'
import { getPropertyValueByPath, stringify } from '../../utils/utils'

// Sync with .../api/person.py and .../lib/constants.tsx
const PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES = ['email', 'Email', 'name', 'Name', 'username', 'Username', 'UserName']

const TOKENS_REGEX_BRACKETS_EXCLUDED = /(?<=(?<!\\){{)(.*?)(?=(?<!\\)}})/g
const TOKENS_REGEX_BRACKETS_INCLUDED = /(?<!\\){{(.*?)(?<!\\)\}}/g

export type MessageFormatterOptions = {
    event: PostIngestionEvent
    team: Team
    siteUrl: string
    sourcePath: string
    sourceName: string
}

// This formatter is "simpler" in that it only supports parsing of a few tokens
export class MessageFormatter {
    private projectUrl: string
    private personLink: string
    private eventLink: string
    private sourceLink: string

    constructor(private options: MessageFormatterOptions) {
        this.projectUrl = `${options.siteUrl}/project/${options.team.id}`

        this.personLink = `${this.projectUrl}/person/${encodeURIComponent(options.event.distinctId)}`
        this.eventLink = `${this.projectUrl}/events/${encodeURIComponent(options.event.eventUuid)}/${encodeURIComponent(
            options.event.timestamp
        )}`

        this.sourceLink = `${this.projectUrl}${options.sourcePath}`
    }

    format(template: string): string {
        const message = this.getFormattedMessage(template)
        return message
    }

    formatSafely(template: unknown): unknown {
        if (typeof template === 'string') {
            return this.getFormattedMessage(template)
        }

        return template
    }

    private getFormattedMessage(template: string): string {
        try {
            const [tokens, tokenizedMessage] = this.getTokens(template)
            const values: string[] = []

            for (const token of tokens) {
                const tokenParts = token.split('.') || []

                const value = this.getValueOfToken(tokenParts)

                console.log(tokenParts, value, tokenizedMessage)
                values.push(value)
            }
            return format(tokenizedMessage, ...values)
        } catch (error) {
            return `⚠ Error: There are one or more formatting errors in the message template for source "${this.options.sourceName} - ${this.sourceLink}".`
        }
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
        return this.escapeMarkdown(stringify(text))
    }

    private getPersonDetails(): string {
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

        return display
    }

    private getGroupLink(groupIndex: number, groupKey: string): string {
        return `${this.projectUrl}/groups/${groupIndex}/${encodeURIComponent(groupKey)}`
    }

    private getTokens(template: string): [string[], string] {
        // This finds property value tokens, basically any string contained in square brackets
        // Examples: "[foo]" is matched in "bar [foo]", "[action.name]" is matched in "action [action.name]"
        // The backslash is used as an escape character - "\[foo\]" is not matched, allowing square brackets in messages
        const matchedTokens = template.match(TOKENS_REGEX_BRACKETS_EXCLUDED) || []
        // Replace the tokens with placeholders, and unescape leftover brackets
        const tokenizedMessage = template.replace(TOKENS_REGEX_BRACKETS_INCLUDED, '%s').replace(/\\({{|}})/g, '$1')
        return [matchedTokens, tokenizedMessage]
    }

    private getValueOfToken(tokenParts: string[]): string {
        let text = ''

        if (tokenParts[0] === 'user') {
            // [user.name] and [user.foo] are DEPRECATED as they had odd mechanics
            // [person] OR [event.properties.bar] should be used instead
            if (tokenParts[1] === 'name') {
                text = this.getPersonDetails()
            } else {
                const propertyName = `$${tokenParts[1]}`
                const property = this.options.event.properties?.[propertyName]
                text = this.webhookEscape(property)
            }
        } else if (tokenParts[0] === 'person') {
            if (tokenParts.length === 1) {
                text = stringify({
                    id: this.options.event.person_id,
                    properties: this.options.event.person_properties,
                    link: this.personLink,
                })
            } else if (tokenParts[1] === 'link') {
                text = this.webhookEscape(this.personLink)
            } else if (tokenParts[1] === 'properties') {
                if (tokenParts.length == 2) {
                    text = stringify(this.options.event.person_properties)
                } else {
                    const property = this.options.event.person_properties
                        ? getPropertyValueByPath(this.options.event.person_properties, tokenParts.slice(2))
                        : undefined
                    text = this.webhookEscape(property)
                }
            }
        } else if (tokenParts[0] === 'action' || tokenParts[0] === 'source') {
            if (tokenParts[1] === 'name') {
                text = this.options.sourceName
            } else if (tokenParts[1] === 'link') {
                text = this.webhookEscape(this.sourceLink)
            }
        } else if (tokenParts[0] === 'event') {
            if (tokenParts.length === 1) {
                // TODO: Standardise this format
                text = stringify({
                    uuid: this.options.event.eventUuid,
                    event: this.options.event.event,
                    timestamp: this.options.event.timestamp,
                    distinct_id: this.options.event.distinctId,
                    link: this.eventLink,
                    properties: this.options.event.properties,
                })
            } else if (tokenParts[1] === 'link') {
                text = this.webhookEscape(this.eventLink)
            } else if (tokenParts[1] === 'uuid') {
                text = this.webhookEscape(this.options.event.eventUuid)
            } else if (tokenParts[1] === 'name') {
                // deprecated
                text = this.webhookEscape(this.options.event.event)
            } else if (tokenParts[1] === 'event') {
                text = this.webhookEscape(this.options.event.event)
            } else if (tokenParts[1] === 'timestamp') {
                text = this.webhookEscape(this.options.event.timestamp)
            } else if (tokenParts[1] === 'distinct_id') {
                text = this.webhookEscape(this.options.event.distinctId)
            } else if (tokenParts[1] === 'properties') {
                if (tokenParts.length === 2) {
                    text = stringify(this.options.event.properties)
                } else {
                    const property = this.options.event.properties
                        ? getPropertyValueByPath(this.options.event.properties, tokenParts.slice(2))
                        : undefined
                    text = this.webhookEscape(property)
                }
            }
        } else if (tokenParts[0] === 'groups') {
            if (tokenParts.length === 1) {
                text = stringify(this.options.event.groups)
            } else if (tokenParts.length > 1) {
                const relatedGroup = this.options.event.groups?.[tokenParts[1]]

                if (!relatedGroup) {
                    // What to return if no matching group?
                    return `(event without group '${tokenParts[1]}')`
                }

                if (tokenParts.length === 2) {
                    // Return the group name
                    // NOTE: group type is not correct...
                    return stringify(relatedGroup)
                } else if (tokenParts[2] === 'key') {
                    text = this.webhookEscape(relatedGroup.key)
                } else if (tokenParts[2] === 'link') {
                    text = this.webhookEscape(this.getGroupLink(relatedGroup.index, relatedGroup.key))
                } else if (tokenParts[2] === 'properties') {
                    if (tokenParts.length === 3) {
                        text = stringify(relatedGroup.properties)
                    } else {
                        const property = relatedGroup.properties
                            ? getPropertyValueByPath(relatedGroup.properties, tokenParts.slice(3))
                            : undefined
                        text = this.webhookEscape(property)
                    }
                }
            }
        } else {
            throw new Error()
        }
        return text
    }
}
