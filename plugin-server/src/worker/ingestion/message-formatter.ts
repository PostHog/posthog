import { PostIngestionEvent, Team } from '../../types'
import { cloneObject, getPropertyValueByPath } from '../../utils/utils'

// Sync with .../api/person.py and .../lib/constants.tsx
const PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES = ['email', 'Email', 'name', 'Name', 'username', 'Username', 'UserName']

const TOKENS_REGEX_BRACKETS_INCLUDED = /(?<!\\){{?(.*?)(?<!\\)}}?/g
const TOKENS_REGEX_DOUBLE_BRACKETS_EXCLUDED = /(?<=(?<!\\){{)(.*?)(?=(?<!\\)}})/g

export type MessageFormatterOptions = {
    event: PostIngestionEvent
    team: Team
    siteUrl: string
    sourcePath: string
    sourceName: string
}

export class MessageFormatter {
    // NOTE: This is our current solution for templating out inputs
    // When we have Hog ready, it will essentially replace the "format" method

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
        // Takes a string and formats it with the event data
        const message = this.getFormattedMessage(template)
        return message
    }

    formatRaw(template: string): any {
        // Strings like "{{foo}}" are treated special and returned as the raw value
        const match = template.match(TOKENS_REGEX_DOUBLE_BRACKETS_EXCLUDED)

        if (match) {
            return this.getValueOfToken(match[0])
        } else {
            return this.format(template)
        }
    }

    formatJSON(template: object): object {
        if (typeof template === 'string') {
            return this.formatRaw(template)
        }

        const returnJSON = cloneObject(template) as any

        // TODO: Support arrays
        for (const [key, value] of Object.entries(returnJSON)) {
            if (typeof value === 'string') {
                returnJSON[key] = this.formatRaw(value)
            } else if (value && typeof value === 'object') {
                returnJSON[key] = this.formatJSON(value)
            }
        }

        return returnJSON
    }

    private getFormattedMessage(template: string): string {
        try {
            const messageParts = template.split(TOKENS_REGEX_BRACKETS_INCLUDED)

            messageParts.forEach((part, index) => {
                if (index % 2 === 0) {
                    // If the index is even, it's a string part
                    return
                }
                // Otherwise its a template part
                const value = this.getValueOfToken(part)
                return (messageParts[index] = typeof value === 'string' ? value : JSON.stringify(value ?? null))
            })

            const message = messageParts
                .join('')
                // Remove any escaped brackets
                .replace(/\\({{?|}}?)/g, '$1')

            return message
        } catch (error) {
            console.error(error)
            return `⚠ Error: There are one or more formatting errors in the message template for source "${this.options.sourceName} - ${this.sourceLink}".`
        }
    }

    private sanitizeString(text: any): string {
        if (typeof text !== 'string') {
            text = JSON.stringify(text)
        }

        if (typeof text === 'undefined') {
            return 'null'
        }

        // As the string will be embedded in a json string value, we need to ensure we have appropriately escaped the string
        // and accounted for any other special characters that could cause issues

        // Escape backslashes
        text = text.replace(/\\/g, '\\\\')
        // Escape double quotes
        text = text.replace(/"/g, '\\"')
        // Escape newlines
        text = text.replace(/\n/g, '\\n')

        return text
    }

    private getPersonDisplay(): string {
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

    private getValueOfToken(token: string): string | object {
        const tokenParts = token.split('.').map((x) => x.trim())

        if (tokenParts[0] === 'user') {
            // [user.name] and [user.foo] are DEPRECATED as they had odd mechanics
            // [person] OR [event.properties.bar] should be used instead
            if (tokenParts[1] === 'name') {
                return this.getPersonDisplay()
            }

            const propertyName = `$${tokenParts[1]}`
            const property = this.options.event.properties?.[propertyName]
            return property
        }
        if (tokenParts[0] === 'project') {
            // [user.name] and [user.foo] are DEPRECATED as they had odd mechanics
            // [person] OR [event.properties.bar] should be used instead
            switch (tokenParts[1]) {
                case 'name':
                    return this.options.team.name
                case 'id':
                    return `${this.options.team.id}`
                case 'link':
                    return this.projectUrl
            }
        }
        if (tokenParts[0] === 'action' || tokenParts[0] === 'source') {
            switch (tokenParts[1]) {
                case 'name':
                    return this.options.sourceName
                case 'link':
                    return this.sourceLink
            }
        }
        if (tokenParts[0] === 'person') {
            if (tokenParts.length === 1) {
                return {
                    id: this.options.event.person_id,
                    properties: this.options.event.person_properties,
                    link: this.personLink,
                }
            }

            switch (tokenParts[1]) {
                case 'name':
                    return this.getPersonDisplay()
                case 'link':
                    return this.personLink
                case 'properties':
                    if (tokenParts.length === 2) {
                        return this.options.event.person_properties
                    }
                    const property = this.options.event.person_properties
                        ? getPropertyValueByPath(this.options.event.person_properties, tokenParts.slice(2))
                        : undefined
                    return property
            }
        }
        if (tokenParts[0] === 'event') {
            if (tokenParts.length === 1) {
                // TODO: Standardise this format
                return {
                    uuid: this.options.event.eventUuid,
                    event: this.options.event.event,
                    timestamp: this.options.event.timestamp,
                    distinct_id: this.options.event.distinctId,
                    link: this.eventLink,
                    properties: this.options.event.properties,
                }
            }

            switch (tokenParts[1]) {
                case 'link':
                    return this.eventLink
                case 'uuid':
                    return this.options.event.eventUuid
                case 'name':
                case 'event':
                    return this.options.event.event
                case 'timestamp':
                    return this.options.event.timestamp
                case 'distinct_id':
                    return this.options.event.distinctId
                case 'properties':
                    if (tokenParts.length === 2) {
                        return this.options.event.properties
                    }
                    const property = this.options.event.properties
                        ? getPropertyValueByPath(this.options.event.properties, tokenParts.slice(2))
                        : undefined
                    return property
            }
        }

        if (tokenParts[0] === 'groups') {
            if (tokenParts.length === 1) {
                return this.options.event.groups ?? '(event without groups)'
            }
            const relatedGroup = this.options.event.groups?.[tokenParts[1]]

            if (!relatedGroup) {
                // What to return if no matching group?
                return `(event without group '${tokenParts[1]}')`
            }

            if (tokenParts.length === 2) {
                return relatedGroup
            }

            switch (tokenParts[2]) {
                case 'key':
                    return relatedGroup.key
                case 'name':
                    return relatedGroup.properties.name ?? relatedGroup.key
                case 'link':
                    return this.getGroupLink(relatedGroup.index, relatedGroup.key)
                case 'properties':
                    if (tokenParts.length === 3) {
                        return relatedGroup.properties
                    }
                    const property = relatedGroup.properties
                        ? getPropertyValueByPath(relatedGroup.properties, tokenParts.slice(3))
                        : undefined
                    return property
            }
        }
        throw new Error('No matching token found in the event data.')
    }
}
