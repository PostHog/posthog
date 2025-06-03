import { DestinationDefinition, destinations } from '@segment/action-destinations'

import { HogFunctionFilterEvent, HogFunctionInputSchemaType } from '~/src/cdp/types'

import { HogFunctionTemplate } from '../templates/types'

export type SegmentDestination = {
    template: HogFunctionTemplate
    destination: DestinationDefinition
}

const translateFilters = (subscribe: string): { events: HogFunctionFilterEvent[] } => {
    const mapped = subscribe
        .replaceAll('type = "page"', 'event = "$pageview"')
        .replaceAll('type = "screen"', 'event = "$screen"')
        .replaceAll('type = "identify"', `event in ('$identify', '$set')`)
        .replaceAll('type = "group"', 'event = "$groupidentify"')
        .replaceAll(
            'type = "track"',
            `event not in ('$pageview', '$screen', '$alias', '$identify', '$set', '$groupidentify')`
        )
        .replaceAll('type = "alias"', 'event = "$alias"')
        .replaceAll(`"`, `'`)

    return {
        events: [
            {
                id: null,
                name: 'All events',
                type: 'events',
                order: 0,
                properties: [
                    {
                        key: mapped,
                        type: 'hogql',
                        value: null,
                    },
                ],
            },
        ],
    }
}

const translateInputs = (defaultVal: any, multiple: boolean = false) => {
    const normalizeValue = (value: string) => {
        let modifiedVal = value

        if (modifiedVal.includes('event.traits')) {
            modifiedVal = modifiedVal.replaceAll('event.traits', 'person.properties')
        }
        if (modifiedVal.includes('event.name')) {
            modifiedVal = modifiedVal.replaceAll('event.name', 'event.event')
        }
        if (modifiedVal.includes('event.context.traits')) {
            modifiedVal = modifiedVal.replaceAll('event.context.traits', 'person.properties')
        }
        if (modifiedVal.includes('event.type')) {
            modifiedVal = modifiedVal.replaceAll(
                'event.type',
                `event.event == '$pageview' ? 'page' : event.event == '$screen' ? 'screen' : event.event == '$groupidentify' ? 'group' : event.event in ('$identify', '$set') ? 'identify' : event.event == '$alias' ? 'alias' : 'track'`
            )
        }
        if (modifiedVal.includes('context.device.type')) {
            modifiedVal = modifiedVal.replaceAll('context.device.type', 'properties.$device_type')
        }
        if (modifiedVal.includes('context.os.name')) {
            modifiedVal = modifiedVal.replaceAll('context.os.name', 'properties.$os')
        }
        if (modifiedVal.includes('context.os.version')) {
            modifiedVal = modifiedVal.replaceAll('context.os.version', 'properties.$os_version')
        }
        if (modifiedVal.includes('context.device.brand')) {
            modifiedVal = modifiedVal.replaceAll('context.device.brand', '')
        }
        if (modifiedVal.includes('context.device.manufacturer')) {
            modifiedVal = modifiedVal.replaceAll('context.device.manufacturer', 'properties.$device_manufacturer')
        }
        if (modifiedVal.includes('context.device.model')) {
            modifiedVal = modifiedVal.replaceAll('context.device.model', 'properties.$device_model')
        }
        if (modifiedVal.includes('context.device.name')) {
            modifiedVal = modifiedVal.replaceAll('context.device.name', 'properties.$device_name')
        }
        if (modifiedVal.includes('context.network.bluetooth')) {
            modifiedVal = modifiedVal.replaceAll('context.network.bluetooth', '')
        }
        if (modifiedVal.includes('context.network.cellular')) {
            modifiedVal = modifiedVal.replaceAll('context.network.cellular', '')
        }
        if (modifiedVal.includes('context.network.wifi')) {
            modifiedVal = modifiedVal.replaceAll('context.network.wifi', '')
        }
        if (modifiedVal.includes('context.network.carrier')) {
            modifiedVal = modifiedVal.replaceAll('context.network.carrier', '')
        }
        if (modifiedVal.includes('context.location.country')) {
            modifiedVal = modifiedVal.replaceAll('context.location.country', 'properties.$geoip_country_name')
        }
        if (modifiedVal.includes('context.location.region')) {
            modifiedVal = modifiedVal.replaceAll('context.location.region', '')
        }
        if (modifiedVal.includes('context.location.city')) {
            modifiedVal = modifiedVal.replaceAll('context.location.city', 'properties.$geoip_city_name')
        }
        if (modifiedVal.includes('context.locale')) {
            modifiedVal = modifiedVal.replaceAll('context.locale', 'properties.$locale')
        }
        if (modifiedVal.includes('context.location.latitude')) {
            modifiedVal = modifiedVal.replaceAll('context.location.latitude', 'properties.$geoip_latitude')
        }
        if (modifiedVal.includes('context.location.longitude')) {
            modifiedVal = modifiedVal.replaceAll('context.location.longitude', 'properties.$geoip_longitude')
        }
        if (modifiedVal.includes('context.ip')) {
            modifiedVal = modifiedVal.replaceAll('context.ip', 'properties.$ip')
        }
        if (modifiedVal.includes('context.device.id')) {
            modifiedVal = modifiedVal.replaceAll('context.device.id', 'properties.$device_id')
        }
        if (modifiedVal.includes('context.library.name')) {
            modifiedVal = modifiedVal.replaceAll('context.library.name', 'properties.$lib')
        }
        if (modifiedVal.includes('context.library.version')) {
            modifiedVal = modifiedVal.replaceAll('context.library.version', 'properties.$lib_version')
        }
        if (modifiedVal.includes('context.page.url')) {
            modifiedVal = modifiedVal.replaceAll('context.page.url', 'properties.$current_url')
        }
        if (modifiedVal.includes('context.page.title')) {
            modifiedVal = modifiedVal.replaceAll('context.page.title', 'properties.title')
        }
        if (modifiedVal.includes('context.page.path')) {
            modifiedVal = modifiedVal.replaceAll('context.page.path', 'properties.$pathname')
        }
        if (modifiedVal.includes('context.page.search')) {
            modifiedVal = modifiedVal.replaceAll('context.page.search', '')
        }
        if (modifiedVal.includes('context.screen.density')) {
            modifiedVal = modifiedVal.replaceAll('context.screen.density', '')
        }
        if (modifiedVal.includes('context.device.adTrackingEnabled')) {
            modifiedVal = modifiedVal.replaceAll('context.device.adTrackingEnabled', '')
        }
        if (modifiedVal.includes('context.timezone')) {
            modifiedVal = modifiedVal.replaceAll('context.timezone', 'properties.$timezone')
        }
        if (modifiedVal.includes('context.userAgentData.model')) {
            modifiedVal = modifiedVal.replaceAll('context.userAgentData.model', '')
        }
        if (modifiedVal.includes('context.userAgentData.platformVersion')) {
            modifiedVal = modifiedVal.replaceAll('context.userAgentData.platformVersion', '')
        }
        if (modifiedVal.includes('context.userAgentData.wow64')) {
            modifiedVal = modifiedVal.replaceAll('context.userAgentData.wow64', '')
        }
        if (modifiedVal.includes('context.userAgentData.mobile')) {
            modifiedVal = modifiedVal.replaceAll('context.userAgentData.mobile', '')
        }
        if (modifiedVal.includes('context.userAgentData.bitness')) {
            modifiedVal = modifiedVal.replaceAll('context.userAgentData.bitness', '')
        }
        if (modifiedVal.includes('context.userAgentData.platform')) {
            modifiedVal = modifiedVal.replaceAll('context.userAgentData.platform', '')
        }
        if (modifiedVal.includes('context.userAgentData.architecture')) {
            modifiedVal = modifiedVal.replaceAll('context.userAgentData.architecture', '')
        }
        if (modifiedVal.includes('context.userAgentData.uaFullVersion')) {
            modifiedVal = modifiedVal.replaceAll('context.userAgentData.uaFullVersion', '')
        }
        if (modifiedVal.includes('context.groupId')) {
            modifiedVal = modifiedVal.replaceAll('context.groupId', '')
        }
        if (modifiedVal.includes('context.userAgent')) {
            modifiedVal = modifiedVal.replaceAll('context.userAgent', 'properties.$raw_user_agent')
        }
        if (modifiedVal.includes('context.page.referrer')) {
            modifiedVal = modifiedVal.replaceAll('context.page.referrer', 'properties.$referrer')
        }
        if (modifiedVal.includes('context.campaign.source')) {
            modifiedVal = modifiedVal.replaceAll('context.campaign.source', 'properties.utm_source')
        }
        if (modifiedVal.includes('context.campaign.medium')) {
            modifiedVal = modifiedVal.replaceAll('context.campaign.medium', 'properties.utm_medium')
        }
        if (modifiedVal.includes('context.campaign.name')) {
            modifiedVal = modifiedVal.replaceAll('context.campaign.name', 'properties.utm_campaign')
        }
        if (modifiedVal.includes('context.campaign.term')) {
            modifiedVal = modifiedVal.replaceAll('context.campaign.term', 'properties.utm_term')
        }
        if (modifiedVal.includes('context.campaign.content')) {
            modifiedVal = modifiedVal.replaceAll('context.campaign.content', 'properties.utm_content')
        }
        if (modifiedVal.includes('context.app.namespace')) {
            modifiedVal = modifiedVal.replaceAll('context.app.namespace', 'event.properties.$app_namespace')
        }
        if (modifiedVal.includes('context.app.name')) {
            modifiedVal = modifiedVal.replaceAll('context.app.name', 'event.properties.$app_name')
        }
        if (modifiedVal.includes('context.app.build')) {
            modifiedVal = modifiedVal.replaceAll('context.app.build', 'event.properties.$app_build')
        }
        if (modifiedVal.includes('context.app.platform')) {
            modifiedVal = modifiedVal.replaceAll('context.app.platform', '')
        }
        if (modifiedVal.includes('context.app.version')) {
            modifiedVal = modifiedVal.replaceAll('context.app.version', 'event.properties.$app_version')
        }
        if (modifiedVal.includes('event.anonymousId')) {
            modifiedVal = modifiedVal.replaceAll('event.anonymousId', 'event.distinct_id')
        }
        if (modifiedVal.includes('context.device.advertisingId')) {
            modifiedVal = modifiedVal.replaceAll('context.device.advertisingId', '')
        }
        if (modifiedVal.includes('integrations.Actions Amplitude.session_id')) {
            modifiedVal = modifiedVal.replaceAll('integrations.Actions Amplitude.session_id', '')
        }
        if (modifiedVal.includes('event.userId')) {
            modifiedVal = modifiedVal.replaceAll('event.userId', 'person.id')
        }
        if (modifiedVal.includes('event.messageId')) {
            modifiedVal = modifiedVal.replaceAll('event.messageId', 'event.uuid')
        }
        if (modifiedVal.includes('integrations.')) {
            modifiedVal = modifiedVal.replaceAll(/integrations\.[^}]+/g, '')
        }
        if (modifiedVal.startsWith('context.')) {
            modifiedVal = modifiedVal.replaceAll('context.', 'event.properties.')
        }

        if (modifiedVal.endsWith('.')) {
            return ''
        } else {
            return modifiedVal
        }
    }

    if (['string'].includes(typeof defaultVal)) {
        return defaultVal
    }
    if (['boolean'].includes(typeof defaultVal)) {
        return defaultVal ? 'true' : 'false'
    }
    if (typeof defaultVal === 'object') {
        if (defaultVal && '@path' in defaultVal) {
            let modifiedVal = defaultVal['@path'].replace('$.', 'event.')

            modifiedVal = normalizeValue(modifiedVal)
            if (modifiedVal === '') {
                return ''
            } else {
                return multiple ? `{[${modifiedVal}]}` : `{${modifiedVal}}`
            }
        } else if (defaultVal && '@if' in defaultVal) {
            if (JSON.stringify(defaultVal['@if'].exists) === JSON.stringify(defaultVal['@if'].then)) {
                let val = defaultVal['@if'].then
                if (typeof val === 'object' && val['@path']) {
                    val = val['@path'].replace('$.', 'event.')
                    val = normalizeValue(val)
                } else if (typeof val === 'string') {
                    val = `'${val}'`
                }

                let fallbackVal = defaultVal['@if'].else
                if (typeof fallbackVal === 'object' && fallbackVal['@path']) {
                    fallbackVal = fallbackVal['@path'].replace('$.', 'event.')
                    fallbackVal = normalizeValue(fallbackVal)
                } else if (typeof fallbackVal === 'string') {
                    fallbackVal = `'${fallbackVal}'`
                }

                if (val === '' && fallbackVal === '') {
                    return ''
                } else if (val === '' && fallbackVal !== '') {
                    return `{${fallbackVal}}`
                } else if (val !== '' && fallbackVal === '') {
                    return `{${val}}`
                } else {
                    return `{${multiple ? '[' : ''}${val} ?? ${fallbackVal}${multiple ? ']' : ''}}`
                }
            }
        } else if (defaultVal && '@arrayPath' in defaultVal) {
            let val = defaultVal['@arrayPath'][0]
            val = val.replace('$.', 'event.')
            return normalizeValue(val)
        }
    }
    return JSON.stringify(defaultVal)
}

const getDefaultValue = (key: string, field: any, mapping?: Record<string, any> | undefined) => {
    const checkOverride = (defaultVal: any, fieldKey: string, nested: boolean = false) => {
        if (mapping) {
            if (nested) {
                if (key in mapping && fieldKey in mapping[key] && !mapping[key][fieldKey]['@template']) {
                    return mapping[key][fieldKey]
                }
            } else {
                if (fieldKey in mapping && !mapping[fieldKey]['@template']) {
                    return mapping[fieldKey]
                }
            }
        }
        return defaultVal
    }

    if (
        field.type === 'object' &&
        (typeof field.default === 'undefined' || !('@path' in field.default || '@arrayPath' in field.default))
    ) {
        return Object.fromEntries(
            Object.entries(field.properties ?? {}).map(([key, { multiple }]: [string, any]) => {
                const defaultVal = (field.default as Record<string, object>) ?? {}
                return [key, translateInputs(checkOverride(defaultVal[key], key, true), multiple)]
            })
        )
    } else {
        return translateInputs(checkOverride(field.default, key), field.multiple)
    }
}

const getFieldType = (field: any) => {
    if (field.choices) {
        return 'choice'
    }

    if (field.type === 'object') {
        if (typeof field.default !== 'undefined' && '@path' in field.default) {
            return 'string'
        }
        if (typeof field.default !== 'undefined' && '@arrayPath' in field.default) {
            return 'string'
        }
        return 'dictionary'
    }

    if (['number', 'integer', 'datetime', 'password', 'boolean'].includes(field.type)) {
        return 'string'
    }

    if (typeof field.default === 'object' && '@path' in field.default) {
        return 'string'
    }

    return field.type ?? 'string'
}

const translateInputsSchema = (
    inputs_schema: Record<string, any> | undefined,
    mapping?: Record<string, any> | undefined
): HogFunctionInputSchemaType[] => {
    if (!inputs_schema) {
        return []
    }
    return Object.entries(inputs_schema)
        .filter(([key]) => !['use_batch_endpoint', 'batch_size', 'enable_batching'].includes(key))
        .map(([key, field]) => ({
            key,
            label: field.label,
            type: getFieldType(field),
            description: field.description,
            default: getDefaultValue(key, field, mapping),
            required: field.required ?? false,
            secret: field.type === 'password' ? true : false,
            ...(field.choices ? { choices: field.choices } : {}),
        })) as HogFunctionInputSchemaType[]
}

// hide all destinations for now
const APPROVED_DESTINATIONS: string[] = [
    // 'segment-mixpanel',
    // 'segment-amplitude',
    // 'segment-launchdarkly',
    // 'segment-canny',
    // 'segment-fullstory-cloud',
    // 'segment-drip',
    // 'segment-heap',
    // 'segment-pipedrive',
]

const HIDDEN_DESTINATIONS = [
    'segment-snap-conversions',
    'segment-google-sheets-dev',
    'segment-google-analytics-4',
    'segment-google-campaign-manager-360',
    'segment-hubspot-cloud',
    'segment-facebook-conversions-api',
    'segment-june-actions',
    'segment-intercom-cloud',
    'segment-avo',
    'segment-loops',
    'segment-google-enhanced-conversions',
    'segment-reddit-conversions-api',
    'segment-customerio',
    'segment-slack',
    'segment-webhook',
    'segment-webhook-extensible',
    'segment-gleap-cloud-actions',
    'segment-adjust',
    'segment-apolloio',
    'segment-attio',
    'segment-braze-cloud',
    'segment-klaviyo',
    'segment-tiktok-conversions',
    'segment-tiktok-conversions-sandbox',
    'segment-tiktok-offline-conversions',
    'segment-tiktok-offline-conversions-sandbox',
]

export const SEGMENT_DESTINATIONS = Object.entries(destinations)
    .filter(([_, destination]) => destination)
    .filter(([_, destination]) => {
        const id =
            'segment-' +
            (destination.slug?.replace('actions-', '') ??
                destination.name.replace('Actions ', '').replaceAll(' ', '-').toLowerCase())
        if (HIDDEN_DESTINATIONS.includes(id) || id.includes('audiences')) {
            return false
        }
        if (
            Object.keys(destination.authentication?.fields ?? {}).length === 0 ||
            (destination?.presets ?? []).length === 0
        ) {
            return false
        }
        return true
    })
    .map(([_, destination]) => {
        const id =
            'segment-' +
            (destination.slug?.replace('actions-', '') ??
                destination.name.replace('Actions ', '').replaceAll(' ', '-').toLowerCase())
        const name = destination.name.replace(' (Actions)', '').replace('Actions ', '')

        return {
            destination,
            template: {
                free: false,
                status: APPROVED_DESTINATIONS.includes(id) ? 'beta' : 'hidden',
                type: 'destination',
                id,
                name,
                description: `Send event data to ${name}`,
                icon_url: `/api/environments/@current/hog_functions/icon/?id=${destination.slug?.split('-')[1]}.com`,
                category: [],
                inputs_schema: [
                    ...translateInputsSchema(destination.authentication?.fields),
                    {
                        key: 'debug_mode',
                        label: 'Debug Mode',
                        type: 'boolean',
                        description: 'Will log configuration and request details',
                        default: false,
                    },
                ],
                hog: 'return event',
                mapping_templates: (destination.presets ?? [])
                    .filter((preset) => preset.type === 'automatic' && preset.subscribe)
                    .filter((preset) => preset.partnerAction in destination.actions)
                    .map((preset) => ({
                        name: preset.name,
                        include_by_default: true,
                        filters:
                            preset.type === 'automatic' && preset.subscribe
                                ? translateFilters(preset.subscribe)
                                : { events: [] },
                        inputs_schema: [
                            ...(preset.partnerAction in destination.actions
                                ? translateInputsSchema(
                                      destination.actions[preset.partnerAction as keyof typeof destination.actions]
                                          .fields,
                                      preset.mapping
                                  )
                                : []),
                            {
                                key: 'internal_partner_action',
                                label: 'Partner Action',
                                hidden: true,
                                type: 'string',
                                default: preset.partnerAction,
                                description: 'The partner action to use',
                                required: true,
                                secret: false,
                            },
                        ],
                    })),
            },
        } as SegmentDestination
    })

export const SEGMENT_DESTINATIONS_BY_ID = SEGMENT_DESTINATIONS.reduce((acc, plugin) => {
    acc[plugin.template.id] = plugin
    return acc
}, {} as Record<string, SegmentDestination>)
