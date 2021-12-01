import { Properties } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import crypto from 'crypto'
import { ProducerRecord } from 'kafkajs'
import { DateTime } from 'luxon'

import { defaultConfig } from '../../config/config'
import { KAFKA_PERSON } from '../../config/kafka-topics'
import { BasePerson, Element, Person, RawPerson, TimestampFormat } from '../../types'
import { castTimestampOrNow } from '../../utils/utils'

export function unparsePersonPartial(person: Partial<Person>): Partial<RawPerson> {
    return { ...(person as BasePerson), ...(person.created_at ? { created_at: person.created_at.toISO() } : {}) }
}

export function escapeQuotes(input: string): string {
    return input.replace(/"/g, '\\"')
}

export function elementsToString(elements: Element[]): string {
    const ret = elements.map((element) => {
        let el_string = ''
        if (element.tag_name) {
            el_string += element.tag_name
        }
        if (element.attr_class) {
            element.attr_class.sort()
            for (const single_class of element.attr_class) {
                el_string += `.${single_class.replace(/"/g, '')}`
            }
        }
        let attributes: Record<string, any> = {
            ...(element.text ? { text: element.text } : {}),
            'nth-child': element.nth_child ?? 0,
            'nth-of-type': element.nth_of_type ?? 0,
            ...(element.href ? { href: element.href } : {}),
            ...(element.attr_id ? { attr_id: element.attr_id } : {}),
            ...element.attributes,
        }
        attributes = Object.fromEntries(
            Object.entries(attributes)
                .sort(([a], [b]) => a.localeCompare(b))
                .map(([key, value]) => [escapeQuotes(key.toString()), escapeQuotes(value.toString())])
        )
        el_string += ':'
        el_string += Object.entries(attributes)
            .map(([key, value]) => `${key}="${value}"`)
            .join('')
        return el_string
    })
    return ret.join(';')
}

// eslint-disable-next-line @typescript-eslint/explicit-module-boundary-types
export function sanitizeEventName(eventName: any): string {
    if (typeof eventName !== 'string') {
        try {
            eventName = JSON.stringify(eventName)
        } catch {
            eventName = String(eventName)
        }
    }
    return eventName.substr(0, 200)
}

/** Escape UTF-8 characters into `\u1234`. */
function jsonEscapeUtf8(s: string): string {
    return s.replace(/[^\x20-\x7F]/g, (x) => '\\u' + ('000' + x.codePointAt(0)?.toString(16)).slice(-4))
}

/** Produce output compatible with that of Python's `json.dumps`. */
function jsonDumps(obj: any): string {
    if (typeof obj === 'object' && obj !== null) {
        if (Array.isArray(obj)) {
            return `[${obj.map(jsonDumps).join(', ')}]` // space after comma
        } else {
            return `{${Object.keys(obj) // no space after '{' or before '}'
                .sort() // must sort the keys of the object!
                .map((k) => `${jsonDumps(k)}: ${jsonDumps(obj[k])}`) // space after ':'
                .join(', ')}}` // space after ','
        }
    } else if (typeof obj === 'string') {
        return jsonEscapeUtf8(JSON.stringify(obj))
    } else {
        return JSON.stringify(obj)
    }
}

export function hashElements(elements: Element[]): string {
    const elementsList = elements.map((element) => ({
        attributes: element.attributes ?? null,
        text: element.text ?? null,
        tag_name: element.tag_name ?? null,
        href: element.href ?? null,
        attr_id: element.attr_id ?? null,
        attr_class: element.attr_class ?? null,
        nth_child: element.nth_child ?? null,
        nth_of_type: element.nth_of_type ?? null,
        order: element.order ?? null,
    }))

    const serializedString = jsonDumps(elementsList)

    return crypto.createHash('md5').update(serializedString).digest('hex')
}

export function chainToElements(chain: string): Element[] {
    const elements: Element[] = []

    // Below splits all elements by ;, while ignoring escaped quotes and semicolons within quotes
    const splitChainRegex = /(?:[^\s;"]|"(?:\\.|[^"])*")+/g

    // Below splits the tag/classes from attributes
    // Needs a regex because classes can have : too
    const splitClassAttributes = /(.*?)($|:([a-zA-Z\-_0-9]*=.*))/g
    const parseAttributesRegex = /((.*?)="(.*?[^\\])")/gm

    Array.from(chain.matchAll(splitChainRegex))
        .map((r) => r[0])
        .forEach((elString, index) => {
            const elStringSplit = Array.from(elString.matchAll(splitClassAttributes))[0]
            const attributes =
                elStringSplit.length > 3
                    ? Array.from(elStringSplit[3].matchAll(parseAttributesRegex)).map((a) => [a[2], a[3]])
                    : []

            const element: Element = {
                attributes: {},
                order: index,
            }

            if (elStringSplit[1]) {
                const tagAndClass = elStringSplit[1].split('.')
                element.tag_name = tagAndClass[0]
                if (tagAndClass.length > 1) {
                    const [_, ...rest] = tagAndClass
                    element.attr_class = rest.filter((t) => t)
                }
            }

            for (const [key, value] of attributes) {
                if (key == 'href') {
                    element.href = value
                } else if (key == 'nth-child') {
                    element.nth_child = parseInt(value)
                } else if (key == 'nth-of-type') {
                    element.nth_of_type = parseInt(value)
                } else if (key == 'text') {
                    element.text = value
                } else if (key == 'attr_id') {
                    element.attr_id = value
                } else if (key) {
                    if (!element.attributes) {
                        element.attributes = {}
                    }
                    element.attributes[key] = value
                }
            }
            elements.push(element)
        })

    return elements
}

export function extractElements(elements: Record<string, any>[]): Element[] {
    return elements.map((el) => ({
        text: el['$el_text']?.slice(0, 400),
        tag_name: el['tag_name'],
        href: el['attr__href']?.slice(0, 2048),
        attr_class: el['attr__class']?.split(' '),
        attr_id: el['attr__id'],
        nth_child: el['nth_child'],
        nth_of_type: el['nth_of_type'],
        attributes: Object.fromEntries(Object.entries(el).filter(([key]) => key.startsWith('attr__'))),
    }))
}

export function timeoutGuard(
    message: string,
    context?: Record<string, any>,
    timeout = defaultConfig.TASK_TIMEOUT * 1000
): NodeJS.Timeout {
    return setTimeout(() => {
        console.log(`⌛⌛⌛ ${message}`, context)
        Sentry.captureMessage(message, context ? { extra: context } : undefined)
    }, timeout)
}

const campaignParams = new Set(['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term', 'gclid'])
const initialParams = new Set([
    '$browser',
    '$browser_version',
    '$device_type',
    '$current_url',
    '$os',
    '$referring_domain',
    '$referrer',
])
const combinedParams = new Set([...campaignParams, ...initialParams])

/** If we get new UTM params, make sure we set those  **/
export function personInitialAndUTMProperties(properties: Properties): Properties {
    const propertiesCopy = { ...properties }
    const maybeSet = Object.entries(properties).filter(([key, value]) => campaignParams.has(key))

    const maybeSetInitial = Object.entries(properties)
        .filter(([key, value]) => combinedParams.has(key))
        .map(([key, value]) => [`$initial_${key.replace('$', '')}`, value])
    if (Object.keys(maybeSet).length > 0) {
        propertiesCopy.$set = { ...(properties.$set || {}), ...Object.fromEntries(maybeSet) }
    }
    if (Object.keys(maybeSetInitial).length > 0) {
        propertiesCopy.$set_once = { ...(properties.$set_once || {}), ...Object.fromEntries(maybeSetInitial) }
    }
    return propertiesCopy
}

/** Returns string in format: ($1, $2, $3, $4, $5, $6, $7, $8, ..., $N) */
export function generatePostgresValuesString(numberOfColumns: number, rowNumber: number): string {
    return (
        '(' +
        Array.from(Array(numberOfColumns).keys())
            .map((x) => `$${x + 1 + rowNumber * numberOfColumns}`)
            .join(', ') +
        ')'
    )
}

export function generateKafkaPersonUpdateMessage(
    createdAt: DateTime | string,
    properties: Properties,
    teamId: number,
    isIdentified: boolean,
    id: string,
    version: number | null,
    isDeleted = 0
): ProducerRecord {
    return {
        topic: KAFKA_PERSON,
        messages: [
            {
                value: Buffer.from(
                    JSON.stringify({
                        id,
                        created_at: castTimestampOrNow(createdAt, TimestampFormat.ClickHouseSecondPrecision),
                        properties: JSON.stringify(properties),
                        team_id: teamId,
                        is_identified: isIdentified,
                        is_deleted: isDeleted,
                        ...(version ? { version } : {}),
                    })
                ),
            },
        ],
    }
}

// Very useful for debugging queries
export function getFinalPostgresQuery(queryString: string, values: any[]): string {
    return queryString.replace(/\$([0-9]+)/g, (m, v) => JSON.stringify(values[parseInt(v) - 1]))
}

export function transformPostgresElementsToEventPayloadFormat(
    rawElements: Record<string, any>[]
): Record<string, any>[] {
    const elementTransformations: Record<string, string> = {
        text: '$el_text',
        attr_class: 'attr__class',
        attr_id: 'attr__id',
        href: 'attr__href',
    }

    const elements = []
    for (const element of rawElements) {
        for (const [key, val] of Object.entries(element)) {
            if (key in elementTransformations) {
                element[elementTransformations[key]] = val
                delete element[key]
            }
        }
        delete element['attributes']
        elements.push(element)
    }

    return elements
}
