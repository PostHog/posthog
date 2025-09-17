import { ProcessedPluginEvent } from '@posthog/plugin-scaffold'

import { LegacyDestinationPluginMeta } from '../../types'

const alias = {
    userId: 'properties.alias',
    previousId: ['properties.distinct_id'],
}

const page = {
    name: 'properties.name',
    'properties.category': 'properties.category',
    'properties.host': 'properties.$host',
    'properties.url': 'properties.$current_url',
    'properties.path': 'properties.$pathname',
    'properties.referrer': 'properties.$referrer',
    'properties.initial_referrer': 'properties.$initial_referrer',
    'properties.referring_domain': 'properties.$referring_domain',
    'properties.initial_referring_domain': 'properties.$initial_referring_domain',
}

const identify = {
    'context.traits': '$set',
    traits: '$set',
}

const group = {
    groupId: 'groupId',
    traits: 'traits',
}

const track = {
    event: 'event',
}

const constants = {
    'context.app.name': 'PostHogPlugin',
    channel: 's2s',
}

// TODO: handle "context.channel" better
const generic = {
    'context.os.name': 'properties.$os',
    'context.browser': 'properties.$browser',
    'context.page.host': 'properties.$host',
    'context.page.url': 'properties.$current_url',
    'context.page.path': 'properties.$pathname',
    'context.page.referrer': 'properties.$referrer',
    'context.page.initial_referrer': 'properties.$initial_referrer',
    'context.page.referring_domain': 'properties.$referring_domain',
    'context.app.version': 'properties.posthog_version',
    'context.page.initial_referring_domain': 'properties.$initial_referring_domain',
    'context.browser_version': 'properties.$browser_version',
    'context.screen.height': 'properties.$screen_height',
    'context.screen.width': 'properties.$screen_width',
    'context.library.name': 'properties.$lib',
    'context.library.version': 'properties.$lib_version',
    'context.ip': 'ip',
    messageId: '$insert_id',
    originalTimestamp: 'timestamp',
    userId: ['$user_id', 'distinct_id'],
    anonymousId: ['properties.$anon_distinct_id', 'properties.$device_id', 'properties.distinct_id'],
    'context.active_feature_flags': 'properties.$active_feature_flags',
    'context.posthog_version': 'properties.posthog_version',
    'context.has_slack_webhook': 'properties.has_slack_webhook',
    'context.token': 'properties.token',
}

const autoCapture = {
    event: 'properties.$event_type',
}

const eventToMapping = {
    $identify: { type: 'identify', mapping: identify },
    $create_alias: { type: 'alias', mapping: alias },
    $pageview: { type: 'page', mapping: page },
    $page: { type: 'page', mapping: page },
    $group: { type: 'group', mapping: group },
    $autocapture: { type: 'track', mapping: autoCapture },
    default: { type: 'track', mapping: track },
}

function set(target: any, path: any, value: any) {
    const keys = path.split('.')
    const len = keys.length

    for (let i = 0; i < len; i++) {
        const prop = keys[i]

        if (!isObject(target[prop])) {
            target[prop] = {}
        }

        if (i === len - 1) {
            result(target, prop, value)
            break
        }

        target = target[prop]
    }
}

function result(target: any, path: any, value: any) {
    target[path] = value
}

function isObject(val: any) {
    return val !== null && (typeof val === 'object' || typeof val === 'function')
}

// Ref: https://github.com/jonschlinkert/get-value
function get(target: any, path: any, options?: any) {
    if (!isObject(options)) {
        options = { default: options }
    }

    if (!isValidObject(target)) {
        return typeof options.default !== 'undefined' ? options.default : target
    }

    if (typeof path === 'number') {
        path = String(path)
    }

    const isArray = Array.isArray(path)
    const isString = typeof path === 'string'
    const splitChar = options.separator || '.'
    const joinChar = options.joinChar || (typeof splitChar === 'string' ? splitChar : '.')

    if (!isString && !isArray) {
        return target
    }

    if (isString && path in target) {
        return isValid(path, target, options) ? target[path] : options.default
    }

    const segs = isArray ? path : split(path, splitChar, options)
    const len = segs.length
    let idx = 0

    do {
        let prop = segs[idx]
        if (typeof prop === 'number') {
            prop = String(prop)
        }

        while (prop && prop.slice(-1) === '\\') {
            prop = join([prop.slice(0, -1), segs[++idx] || ''], joinChar, options)
        }

        if (prop in target) {
            if (!isValid(prop, target, options)) {
                return options.default
            }

            target = target[prop]
        } else {
            let hasProp = false
            let n = idx + 1

            while (n < len) {
                prop = join([prop, segs[n++]], joinChar, options)

                if ((hasProp = prop in target)) {
                    if (!isValid(prop, target, options)) {
                        return options.default
                    }

                    target = target[prop]
                    idx = n - 1
                    break
                }
            }

            if (!hasProp) {
                return options.default
            }
        }
    } while (++idx < len && isValidObject(target))

    if (idx === len) {
        return target
    }

    return options.default
}

function join(segs: any, joinChar: any, options: any) {
    if (typeof options.join === 'function') {
        return options.join(segs)
    }
    return segs[0] + joinChar + segs[1]
}

function split(path: any, splitChar: any, options: any) {
    if (typeof options.split === 'function') {
        return options.split(path)
    }
    return path.split(splitChar)
}

function isValid(key: any, target: any, options: any) {
    if (typeof options.isValid === 'function') {
        return options.isValid(key, target)
    }
    return true
}

function isValidObject(val: any) {
    return isObject(val) || Array.isArray(val) || typeof val === 'function'
}

type RudderstackMeta = LegacyDestinationPluginMeta & {
    global: {
        rudderAuthHeader: { headers: { Authorization: string } }
        writeKey: string
        dataPlaneUrl: string
    }
    config: {
        dataPlaneUrl: string
        writeKey: string
    }
}

export async function setupPlugin({ config, global }: RudderstackMeta) {
    const rudderBase64AuthToken = Buffer.from(`${config.writeKey}:`).toString('base64')

    global.rudderAuthHeader = {
        headers: {
            Authorization: `Basic ${rudderBase64AuthToken}`,
        },
    }
    global.writeKey = config.writeKey
    global.dataPlaneUrl = config.dataPlaneUrl
    return Promise.resolve()
}

export async function onEvent(event: ProcessedPluginEvent, { global, fetch }: RudderstackMeta) {
    const payload = {
        batch: [constructRudderPayload(event)],
        sentAt: new Date().toISOString(),
    }

    await fetch(global.dataPlaneUrl, {
        headers: {
            'Content-Type': 'application/json',
            ...global.rudderAuthHeader.headers,
        },
        body: JSON.stringify(payload),
        method: 'POST',
    })
}

function constructRudderPayload(event: ProcessedPluginEvent) {
    const rudderPayload = {}
    // add const value props
    constructPayload(rudderPayload, event, constants, true)

    // add generic props
    constructPayload(rudderPayload, event, generic)

    // get specific event props
    const eventName = get(event, 'event')
    const { type, mapping } = eventToMapping[eventName as keyof typeof eventToMapping]
        ? eventToMapping[eventName as keyof typeof eventToMapping]
        : eventToMapping['default']

    //set Rudder payload type
    set(rudderPayload, 'type', type)

    // set Rudder event props
    constructPayload(rudderPayload, event, mapping)

    // add all pther posthog keys under props not starting with $ to Rudder payload properties
    Object.keys(event.properties).forEach((propKey) => {
        if (propKey.slice(0, 1) != '$' && event.properties[propKey] != undefined && event.properties[propKey] != null) {
            set(rudderPayload, `properties.${propKey}`, event.properties[propKey])
        }
    })

    return rudderPayload
}

function constructPayload(outPayload: any, inPayload: any, mapping: any, direct = false) {
    Object.keys(mapping).forEach((rudderKeyPath) => {
        const pHKeyPath = mapping[rudderKeyPath]
        let pHKeyVal = undefined
        if (direct) {
            pHKeyVal = pHKeyPath
        } else if (Array.isArray(pHKeyPath)) {
            for (let i = 0; i < pHKeyPath.length; i++) {
                pHKeyVal = get(inPayload, pHKeyPath[i])
                if (pHKeyVal) {
                    break
                }
            }
        } else {
            pHKeyVal = get(inPayload, pHKeyPath)
        }
        if (pHKeyVal != undefined && pHKeyVal != null) {
            set(outPayload, rudderKeyPath, pHKeyVal)
        }
    })
}
