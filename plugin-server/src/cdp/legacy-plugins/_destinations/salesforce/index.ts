import { URL } from 'url'

import { ProcessedPluginEvent } from '@posthog/plugin-scaffold'
import { Properties, RetryError } from '@posthog/plugin-scaffold'

import { parseJSON } from '../../../../utils/json-parse'
import type { FetchResponse } from '../../../../utils/request'
import { LegacyDestinationPluginMeta } from '../../types'

export interface EventSink {
    salesforcePath: string
    propertiesToInclude: string
    method: string
    // NOTE: originally fieldMappings was not included, it should always be included now,
    // but is optional for backwards compatibility
    fieldMappings?: FieldMappings
}

export type FieldMappings = Record<string, string>

export type EventToSinkMapping = Record<string, EventSink>

export const parseEventSinkConfig = (config: SalesforcePluginConfig): EventToSinkMapping | null => {
    let eventMapping: EventToSinkMapping | null = null
    if (config.eventEndpointMapping?.length > 0) {
        try {
            eventMapping = parseJSON(config.eventEndpointMapping) as EventToSinkMapping
        } catch (e) {
            throw new Error('eventEndpointMapping must be an empty string or contain valid JSON!')
        }
    }
    return eventMapping
}

const CACHE_TTL = 60 * 60 * 5 // in seconds

export interface SalesforcePluginConfig {
    salesforceHost: string
    eventPath: string
    eventMethodType: string
    username: string
    password: string
    consumerKey: string
    consumerSecret: string
    eventsToInclude: string
    propertiesToInclude: string
    debugLogging: string
    eventEndpointMapping: string
}

export type SalesforceMeta = LegacyDestinationPluginMeta & {
    config: SalesforcePluginConfig
}

const validateEventSinkConfig = (config: SalesforcePluginConfig): void => {
    const eventMapping = parseEventSinkConfig(config)

    if (eventMapping !== null) {
        Object.entries(eventMapping).map((entry) => {
            const eventSink = entry[1]
            if (eventSink.salesforcePath == null || eventSink.salesforcePath.trim() === '') {
                throw new Error('You must provide a salesforce path for each mapping in config.eventEndpointMapping.')
            }
            if (eventSink.method == null || eventSink.method.trim() === '') {
                throw new Error('You must provide a method for each mapping in config.eventEndpointMapping.')
            }
        })
    } else {
        // if no eventMapping is provided then we still need to receive eventsToInclude
        if (!config.eventsToInclude) {
            throw new Error('If you are not providing an eventEndpointMapping then you must provide events to include.')
        }
        if (!config.eventPath) {
            throw new Error(
                'If you are not providing an eventEndpointMapping then you must provide the salesforce path.'
            )
        }
    }
    // don't send v1 and v2 mapping
    if (eventMapping !== null && !!config.eventsToInclude?.trim()) {
        throw new Error('You should not provide both eventsToInclude and eventMapping.')
    }
}

export function verifyConfig({ config }: SalesforceMeta): void {
    validateEventSinkConfig(config)

    if (!config.salesforceHost) {
        throw new Error('host not provided!')
    }

    try {
        new URL(config.salesforceHost)
    } catch (error) {
        throw new Error('host not a valid URL!')
    }

    if (!config.salesforceHost.startsWith('http')) {
        throw new Error('host not a valid URL!')
    }

    if (!config.username) {
        throw new Error('Username not provided!')
    }

    if (!config.password) {
        throw new Error('Password not provided!')
    }
}

const callSalesforce = async ({
    host,
    sink,
    token,
    event,
    meta,
}: {
    host: string
    sink: EventSink
    token: string
    event: ProcessedPluginEvent
    meta: SalesforceMeta
}): Promise<void> => {
    const response = await meta.fetch(`${host}/${sink.salesforcePath}`, {
        method: sink.method,
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(getProperties(event, sink.propertiesToInclude, sink.fieldMappings)),
    })

    const isOk = statusOk(response, meta.logger)
    if (!isOk) {
        throw new Error(`Not a 200 response from event hook ${response.status}. Response: ${JSON.stringify(response)}`)
    }
}

export async function sendEventToSalesforce(
    event: ProcessedPluginEvent,
    meta: SalesforceMeta,
    token: string
): Promise<void> {
    try {
        const { config, logger } = meta

        logger.debug('processing event: ', event?.event)

        const eventMapping = parseEventSinkConfig(config)

        let eventSink: EventSink
        if (eventMapping !== null) {
            const hasMappingForThisEvent = event.event in eventMapping

            if (!hasMappingForThisEvent || !event.properties) {
                return
            }

            eventSink = eventMapping[event.event]
            logger.debug('v2: processing event: ', event?.event, ' with sink ', eventSink)
        } else {
            const eventsToInclude = config.eventsToInclude.split(',').map((e) => e.trim())
            if (!eventsToInclude.includes(event.event)) {
                return
            }

            eventSink = {
                salesforcePath: config.eventPath,
                method: config.eventMethodType,
                propertiesToInclude: config.propertiesToInclude,
                fieldMappings: {},
            }
            logger.debug('v1: processing event: ', event?.event, ' with sink ', eventSink)
        }

        return callSalesforce({
            host: config.salesforceHost,
            sink: eventSink,
            token,
            event,
            meta,
        })
    } catch (error) {
        meta.logger.error('error while sending event to salesforce. event: ', event.event, ' the error was ', error)
        throw error
    }
}

async function getToken(meta: SalesforceMeta): Promise<string> {
    const { global } = meta

    let token = global.token

    if (!token || token.expiresAt < Date.now()) {
        token = await generateToken(meta)
        global.token = token
        global.expiresAt = Date.now() + CACHE_TTL * 1000
    }
    return token
}

async function generateToken({ config, logger, fetch }: SalesforceMeta): Promise<string> {
    const details: Record<string, string> = {
        grant_type: 'password',
        client_id: config.consumerKey,
        client_secret: config.consumerSecret,
        username: config.username,
        password: config.password,
    }

    const formBody = []
    for (const property in details) {
        const encodedKey = encodeURIComponent(property)
        const encodedValue = encodeURIComponent(details[property])
        formBody.push(encodedKey + '=' + encodedValue)
    }

    const tokenURL = `${config.salesforceHost}/services/oauth2/token`
    logger.debug('getting token from ', tokenURL)
    const response = await fetch(tokenURL, {
        method: 'post',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: formBody.join('&'),
    })

    if (!statusOk(response, logger)) {
        throw new Error(`Got bad response getting the token ${response.status}`)
    }
    const body = await response.json()

    return body.access_token
}

export async function setupPlugin(meta: SalesforceMeta): Promise<void> {
    const { logger } = meta

    verifyConfig(meta)

    try {
        await getToken(meta)
    } catch (error) {
        logger.error('error in getToken', error)
        throw new RetryError('Failed to getToken. cache or salesforce is unavailable')
    }
}

function configToMatchingEvents(config: SalesforcePluginConfig): string[] {
    if (config.eventsToInclude) {
        return config.eventsToInclude.split(',').map((e: string) => e.trim())
    } else {
        return Object.keys(parseJSON(config.eventEndpointMapping)).map((e: string) => e.trim())
    }
    return []
}

export function shouldSendEvent(event: ProcessedPluginEvent, meta: SalesforceMeta): boolean {
    const { config } = meta
    const eventsToMatch = configToMatchingEvents(config)
    return eventsToMatch.includes(event.event)
}

export async function onEvent(event: ProcessedPluginEvent, meta: SalesforceMeta): Promise<void> {
    if (!shouldSendEvent(event, meta)) {
        return
    }

    await sendEventToSalesforce(event, meta, await getToken(meta))
}

function statusOk(res: FetchResponse, logger: SalesforceMeta['logger']): boolean {
    logger.debug('testing response for whether it is "ok". has status: ', res.status, ' debug: ', JSON.stringify(res))
    return String(res.status)[0] === '2'
}

// we allow `any` since we don't know what type the properties are, and `unknown` is too restrictive here

function getNestedProperty(properties: Record<string, any>, path: string): any {
    return path.split('.').reduce((acc, part) => acc[part], properties)
}

export function getProperties(
    event: ProcessedPluginEvent,
    propertiesToInclude: string,
    fieldMappings: FieldMappings = {}
): Properties {
    const { properties } = event

    if (!properties) {
        return {}
    }

    // if no propertiesToInclude is set then all properties are allowed
    const propertiesAllowList = !!propertiesToInclude?.trim().length
        ? propertiesToInclude.split(',').map((e) => e.trim())
        : Object.keys(properties)

    const mappedProperties: Record<string, any> = {}

    propertiesAllowList.forEach((allowedProperty) => {
        const val = getNestedProperty(properties, allowedProperty)
        const mappedKey = fieldMappings[allowedProperty] || allowedProperty
        mappedProperties[mappedKey] = val
    })

    return mappedProperties
}
