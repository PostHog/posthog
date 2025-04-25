import { ProcessedPluginEvent } from '@posthog/plugin-scaffold'
import { destinations } from '@segment/action-destinations/dist/destinations'

import { HogFunctionMappingTemplate } from '~/src/cdp/templates/types'
import { HogFunctionFilterEvent, HogFunctionInputSchemaType } from '~/src/cdp/types'

import { LegacyDestinationPlugin, LegacyDestinationPluginMeta } from './types'

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

const translateInputs = (defaultVal: any) => {
    const normalizeValue = (value: string) => {
        let modifiedVal = value

        if (modifiedVal.includes('event.traits')) {
            modifiedVal = modifiedVal.replaceAll('event.traits', 'person.properties')
        }
        if (modifiedVal.includes('event.context.traits')) {
            modifiedVal = modifiedVal.replaceAll('event.context.traits', 'person.properties')
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

        if (modifiedVal.endsWith('.')) {
            return ''
        } else {
            return modifiedVal
        }
    }

    if (['boolean', 'string'].includes(typeof defaultVal)) {
        return defaultVal
    }
    if (typeof defaultVal === 'object') {
        if (defaultVal && '@path' in defaultVal) {
            let modifiedVal = defaultVal['@path'].replace('$.', 'event.')

            modifiedVal = normalizeValue(modifiedVal)
            if (modifiedVal === '') {
                return ''
            } else {
                return `{${modifiedVal}}`
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
                    return `{${val} ?? ${fallbackVal}}`
                }
            } else {
                return JSON.stringify(defaultVal)
            }
        }
        return JSON.stringify(defaultVal)
    }
    return JSON.stringify(defaultVal)
}

const translateInputsSchema = (inputs_schema: Record<string, any> | undefined): HogFunctionInputSchemaType[] => {
    if (!inputs_schema) {
        return []
    }
    return Object.entries(inputs_schema)
        .filter(([key]) => !['use_batch_endpoint', 'batch_size', 'enable_batching'].includes(key))
        .map(([key, field]) => ({
            key,
            label: field.label,
            type: field.choices
                ? 'choice'
                : field.type === 'object'
                ? typeof field.default !== 'undefined' && '@path' in field.default
                    ? 'string'
                    : 'dictionary'
                : ['number', 'integer', 'datetime', 'password'].includes(field.type)
                ? 'string'
                : typeof field.default === 'object' && '@path' in field.default
                ? 'string'
                : field.type ?? 'string',
            description: field.description,
            default:
                field.type !== 'object' || (typeof field.default !== 'undefined' && '@path' in field.default)
                    ? translateInputs(field.default)
                    : Object.fromEntries(
                          Object.entries(field.properties ?? {}).map(([key, _]) => {
                              const defaultVal = (field.default as Record<string, object>) ?? {}
                              return [key, translateInputs(defaultVal[key])]
                          })
                      ),
            required: field.required ?? false,
            secret: field.type === 'password' ? true : false,
            ...(field.choices ? { choices: field.choices } : {}),
        })) as HogFunctionInputSchemaType[]
}

export const SEGMENT_DESTINATIONS = Object.entries(destinations)
    .filter(([_, destination]) => destination)
    .map(([_, destination]) => {
        return {
            /* eslint-disable-next-line @typescript-eslint/require-await */
            onEvent: async (
                _event: ProcessedPluginEvent,
                { config, fetch, logger }: LegacyDestinationPluginMeta
            ): Promise<void> => {
                logger.warn('config', config)
                try {
                    destination.actions[config.internal_partner_action as keyof typeof destination.actions].perform(
                        async (endpoint, options) => {
                            const requestExtension = destination.extendRequest?.({
                                settings: config as any,
                                auth: config as any,
                                payload: config as any,
                            })
                            logger.warn('requestExtension', requestExtension)
                            logger.warn('endpoint', endpoint)
                            logger.warn('options', options)
                            const headers: Record<string, string> = {
                                endpoint: endpoint,
                                ...options?.headers,
                                ...requestExtension?.headers,
                            }

                            let body: string | URLSearchParams = ''

                            if (options?.json) {
                                body = JSON.stringify(options.json)
                                headers['Content-Type'] = 'application/json'
                            } else if (options?.body && options.body instanceof URLSearchParams) {
                                body = options.body
                                headers['Content-Type'] = 'application/x-www-form-urlencoded'
                            }

                            await fetch(endpoint, {
                                method: options?.method ?? 'POST',
                                headers,
                                body,
                            })
                            return Promise.resolve({} as any)
                        },
                        {
                            payload: config,
                            settings: config,
                        }
                    )
                } catch (e) {
                    logger.error('error', e)
                }
            },
            template: {
                free: false,
                status: 'beta',
                type: 'destination',
                id:
                    destination.slug?.replace('actions-', 'plugin-segment-') ??
                    `plugin-segment-${destination.name.replace('Actions ', '').replaceAll(' ', '-').toLowerCase()}`,
                name: destination.name.replace(' (Actions)', '').replace('Actions ', ''),
                description: `Send event data to ${destination.name.replace(' (Actions)', '').replace('Actions ', '')}`,
                icon_url: `https://img.logo.dev/${destination.slug?.split('-')[1]}.com?token=pk_NiEhY0r4ToO7w_3DQvOALw`,
                category: [],
                inputs_schema: translateInputsSchema(destination.authentication?.fields),
                hog: 'return event',
                mapping_templates: (destination.presets ?? [])
                    .filter((preset) => preset.type === 'automatic')
                    .filter((preset) => preset.partnerAction in destination.actions)
                    .map((preset) => ({
                        name: preset.name,
                        include_by_default: true,
                        filters: translateFilters(preset.subscribe),
                        inputs_schema: [
                            ...(preset.partnerAction in destination.actions
                                ? translateInputsSchema(
                                      destination.actions[preset.partnerAction as keyof typeof destination.actions]
                                          .fields
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
                    })) as HogFunctionMappingTemplate[],
            },
        } as LegacyDestinationPlugin
    })
