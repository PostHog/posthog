import { HogFunctionFilterEvent, HogFunctionInputSchemaType } from '~/src/cdp/types';
import { LegacyDestinationPlugin, LegacyDestinationPluginMeta } from '../../types'
import segmentDestination from './index'
import { ProcessedPluginEvent } from '@posthog/plugin-scaffold';
import { HogFunctionMappingTemplate } from '~/src/cdp/templates/types';

const translateFilters = (subscribe: string): HogFunctionFilterEvent[] => {
    let mapped = subscribe
        .replaceAll('type = "page"', 'event = "$pageview"')
        .replaceAll('type = "screen"', 'event = "$screen"')
        .replaceAll('type = "identify"', 'event = "$identify"')
        .replaceAll('type = "group"', 'event = "$groupidentify"')
        .replaceAll('type = "track"', 'true')
        .replaceAll(`"`, `'`)

    return [
        {
            "id": null,
            "name": "All events",
            "type": "events",
            "order": 0,
            "properties": [
                {
                    "key": mapped,
                    "type": "hogql",
                    "value": null
                }
            ]
        }
    ]
}

const translateInputs = (defaultVal: any) => {
    const normalizeValue = (value: string) => {
        let modifiedVal = value

        if (modifiedVal.includes('event.traits')) {
            modifiedVal = modifiedVal.replaceAll('event.traits', 'person.properties')
        }
        if (modifiedVal.includes('context.app.version')) {
            modifiedVal = modifiedVal.replaceAll('context.app.version', 'properties.$app_version')
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
        if (modifiedVal.includes('context.userAgentData.model')) {
            modifiedVal = modifiedVal.replaceAll('context.userAgentData.model', '')
        }
        if (modifiedVal.includes('context.userAgentData.platformVersion')) {
            modifiedVal = modifiedVal.replaceAll('context.userAgentData.platformVersion', '')
        }
        if (modifiedVal.includes('context.userAgent')) {
            modifiedVal = modifiedVal.replaceAll('context.userAgent', 'properties.$raw_user_agent')
        }
        if (modifiedVal.includes('context.page.referrer')) {
            modifiedVal = modifiedVal.replaceAll('context.page.referrer', 'properties.$referrer')
        }
        if (modifiedVal.includes('context.campaign.source')) {
            modifiedVal = modifiedVal.replaceAll('context.campaign.source', 'properties.$utm_source')
        }
        if (modifiedVal.includes('context.campaign.medium')) {
            modifiedVal = modifiedVal.replaceAll('context.campaign.medium', 'properties.$utm_medium')
        }
        if (modifiedVal.includes('context.campaign.name')) {
            modifiedVal = modifiedVal.replaceAll('context.campaign.name', 'properties.$utm_campaign')
        }
        if (modifiedVal.includes('context.campaign.term')) {
            modifiedVal = modifiedVal.replaceAll('context.campaign.term', 'properties.$utm_term')
        }
        if (modifiedVal.includes('context.campaign.content')) {
            modifiedVal = modifiedVal.replaceAll('context.campaign.content', 'utm_content')
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
            modifiedVal = modifiedVal.replaceAll('event.userId', 'event.distinct_id')
        }

        if (modifiedVal.endsWith('.')) return ''
        else return modifiedVal
    }

    if (['boolean', 'string'].includes(typeof defaultVal)) {
        return defaultVal
    }
    if (typeof defaultVal === 'object') {
        if (defaultVal && '@path' in defaultVal) {
            let modifiedVal = defaultVal['@path']
                .replace('$.', 'event.')

            modifiedVal = normalizeValue(modifiedVal)
            if (modifiedVal === '') return ''
            else return `{${modifiedVal}}`
        } else if (defaultVal && '@if' in defaultVal) {
            if (JSON.stringify(defaultVal['@if'].exists) === JSON.stringify(defaultVal['@if'].then)) {
                let val = defaultVal['@if'].then['@path']
                    .replace('$.', 'event.')

                    val = normalizeValue(val)

                let fallbackVal = defaultVal['@if'].else['@path']
                    .replace('$.', 'event.')
                fallbackVal = normalizeValue(fallbackVal)

                if (val === '' && fallbackVal === '') return ''
                else if (val === '' && fallbackVal !== '') return `{${fallbackVal}}`
                else if (val !== '' && fallbackVal === '') return `{${val}}`
                else return `{${val} ?? ${fallbackVal}}`
            } else {
                return JSON.stringify(defaultVal)
            }
        }
        return JSON.stringify(defaultVal)
    }
    return JSON.stringify(defaultVal)
}

const translateInputsSchema = (inputs_schema: Record<string, any> | undefined): HogFunctionInputSchemaType[] => {
    if (!inputs_schema) return []
    return Object.entries(inputs_schema).map(([key, field]) => ({
        key,
        label: field.label,
        type: field.choices ? 'choice'
            : field.type === 'object' ? 'dictionary'
            : ['number', 'integer', 'datetime'].includes(field.type) ? 'string'
            : field.type ?? 'string',
        description: field.description,
        default: field.type !== 'object' ? translateInputs(field.default) : Object.fromEntries(Object.entries(field.properties ?? {}).map(([key, _]) => {
            const defaultVal = field.default as Record<string, object> ?? {}
            return [key, translateInputs(defaultVal[key])]
        })),
        required: field.required ?? false,
        secret: false,
        ...(field.choices ? { choices: field.choices } : {}),
    })) as HogFunctionInputSchemaType[]
}

export const amplitudePlugin: LegacyDestinationPlugin = {
    onEvent: async (
        _event: ProcessedPluginEvent,
        { config, fetch, logger }: LegacyDestinationPluginMeta
    ): Promise<void> =>  {
        segmentDestination.actions.logEventV2.perform(async (endpoint, options) => {
            await fetch(endpoint, {
                method: options?.method ?? "POST",
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(options?.json),
            })
            return Promise.resolve({} as any)
        }, {
            payload: {
                userId: 'test-user-wxpys9',
                event: 'PostHog Test Event Name',
                properties: {
                    property1: 1,
                    property2: 'test',
                    property3: true
                }
            },
            settings: {
                apiKey: config.apiKey,
                endpoint: config.endpoint,
                secretKey: config.secretKey
            }
        })
    },
    template: {
        free: false,
        status: 'beta',
        type: 'destination',
        id: segmentDestination.slug?.replace('actions-', 'plugin-segment-') ?? `plugin-segment-${segmentDestination.name.replace('Actions ', '').replaceAll(' ', '-').toLowerCase()}`,
        name: segmentDestination.name.replace('Actions ', ''),
        description: `Send event data to ${segmentDestination.name.replace('Actions ', '')}`,
        icon_url: `https://img.logo.dev/${segmentDestination.slug?.split('-')[1]}.com?token=pk_NiEhY0r4ToO7w_3DQvOALw`,
        category: [],
        inputs_schema: translateInputsSchema(segmentDestination.authentication?.fields),
        hog: 'return event',
        mapping_templates: (segmentDestination.presets ?? [])
            .filter((preset) => preset.type === 'automatic')
            .map((preset) => ({
                name: preset.partnerAction,
                include_by_default: true,
                filters: {
                    events: translateFilters(preset.subscribe)
                },
                inputs_schema: translateInputsSchema(segmentDestination.actions.logEventV2.fields)
            })) as HogFunctionMappingTemplate[]
    }
}
