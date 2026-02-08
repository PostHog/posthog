import { ProcessedPluginEvent, RetryError } from '@posthog/plugin-scaffold'

import { FetchResponse } from '../../../../utils/request'
import { LegacyDestinationPluginMeta } from '../../types'

type IntercomMeta = LegacyDestinationPluginMeta & {
    global: {
        intercomUrl: string
    }
    config: {
        intercomApiKey: string
        triggeringEvents: string
        ignoredEmailDomains: string
        useEuropeanDataStorage: string
    }
}

export async function onEvent(event: ProcessedPluginEvent, meta: IntercomMeta): Promise<void> {
    if (!isTriggeringEvent(meta.config.triggeringEvents, event.event)) {
        return
    }

    const intercomUrl =
        meta.config.useEuropeanDataStorage === 'Yes' ? 'https://api.eu.intercom.com' : 'https://api.intercom.io'

    const email = getEmailFromEvent(event)
    if (!email) {
        meta.logger.warn(
            `'${event.event}' will not be sent to Intercom because distinct_id is not an email and no 'email' was found in the event properties.`
        )
        meta.logger.debug(`Skipped event with UUID ${event.uuid}`)
        return
    }

    if (isIgnoredEmailDomain(meta.config.ignoredEmailDomains, email)) {
        return
    }

    const timestamp = getTimestamp(meta, event)

    const isContactInIntercom = await searchForContactInIntercom(meta, intercomUrl, meta.config.intercomApiKey, email)
    if (!isContactInIntercom) {
        return
    }
    await sendEventToIntercom(
        meta,
        intercomUrl,
        meta.config.intercomApiKey,
        email,
        event.event,
        event['distinct_id'],
        timestamp
    )
}

async function searchForContactInIntercom(meta: IntercomMeta, url: string, apiKey: string, email: string) {
    const searchContactResponse = await fetchWithRetry(
        meta,
        `${url}/contacts/search`,
        {
            headers: {
                Accept: 'application/json',
                'Content-Type': 'application/json',
                Authorization: `Bearer ${apiKey}`,
            },
            body: JSON.stringify({
                query: {
                    field: 'email',
                    operator: '=',
                    value: email,
                },
            }),
        },
        'POST'
    )
    const searchContactResponseJson = await searchContactResponse.json()

    if (!statusOk(searchContactResponse) || searchContactResponseJson.errors) {
        const errorMessage = searchContactResponseJson.errors ? searchContactResponseJson.errors[0].message : ''
        meta.logger.error(
            `Unable to search contact ${email} in Intercom. Status Code: ${searchContactResponseJson.status}. Error message: ${errorMessage}`
        )
        return false
    } else {
        const found = searchContactResponseJson['total_count'] > 0
        meta.logger.log(`Contact ${email} in Intercom ${found ? 'found' : 'not found'}`)
        return found
    }
}

async function sendEventToIntercom(
    meta: IntercomMeta,
    url: string,
    apiKey: string,
    email: string,
    event: string,
    distinct_id: string,
    eventSendTime: number
) {
    const sendEventResponse = await fetchWithRetry(
        meta,
        `${url}/events`,
        {
            headers: {
                Accept: 'application/json',
                'Content-Type': 'application/json',
                Authorization: `Bearer ${apiKey}`,
            },
            body: JSON.stringify({
                event_name: event,
                created_at: eventSendTime,
                email,
                id: distinct_id,
            }),
        },
        'POST'
    )

    if (!statusOk(sendEventResponse)) {
        let errorMessage = ''
        try {
            const sendEventResponseJson = await sendEventResponse.json()
            errorMessage = sendEventResponseJson.errors ? sendEventResponseJson.errors[0].message : ''
        } catch {}
        meta.logger.error(
            `Unable to send event ${event} for ${email} to Intercom. Status Code: ${sendEventResponse.status}. Error message: ${errorMessage}`
        )
    } else {
        meta.logger.log(`Sent event ${event} for ${email} to Intercom`)
    }
}

async function fetchWithRetry(meta: IntercomMeta, url: string, options = {}, method = 'GET'): Promise<FetchResponse> {
    try {
        const res = await meta.fetch(url, { method: method, ...options })
        return res
    } catch {
        throw new RetryError('Service is down, retry later')
    }
}

function statusOk(res: FetchResponse) {
    return String(res.status)[0] === '2'
}

function isEmail(email: string): boolean {
    const re =
        /^(([^<>()[\]\\.,;:\s@"]+(\.[^<>()[\]\\.,;:\s@"]+)*)|(".+"))@((\[[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\])|(([a-zA-Z\-0-9]+\.)+[a-zA-Z]{2,}))$/
    return re.test(String(email).toLowerCase())
}

function getEmailFromEvent(event: ProcessedPluginEvent): string | null {
    if (isEmail(event.distinct_id)) {
        return event.distinct_id
    } else if (event['$set'] && Object.keys(event['$set']).includes('email')) {
        if (isEmail(event['$set']['email'])) {
            return event['$set']['email']
        }
    } else if (event['properties'] && Object.keys(event['properties']).includes('email')) {
        if (isEmail(event['properties']['email'])) {
            return event['properties']['email']
        }
    }

    return null
}

function isIgnoredEmailDomain(ignoredEmailDomains: string, email: string): boolean {
    const emailDomainsToIgnore = (ignoredEmailDomains || '').split(',').map((e) => e.trim())
    return emailDomainsToIgnore.includes(email.split('@')[1])
}

function isTriggeringEvent(triggeringEvents: string, event: string): boolean {
    const validEvents = (triggeringEvents || '').split(',').map((e) => e.trim())
    return validEvents.indexOf(event) >= 0
}

function getTimestamp(meta: IntercomMeta, event: ProcessedPluginEvent): number {
    try {
        if (event['timestamp']) {
            return Number(event['timestamp'])
        }
    } catch {
        meta.logger.error('Event timestamp cannot be parsed as a number')
    }
    const date = new Date()
    return Math.floor(date.getTime() / 1000)
}
