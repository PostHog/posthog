import { URLSearchParams } from 'url'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { LegacyTransformationPluginMeta } from '../../types'

export type PluginConfig = {
    ignoreCase: 'true' | 'false'
    prefix: string
    setAsInitialUserProperties: 'true' | 'false'
    setAsUserProperties: 'true' | 'false'
    suffix: string
    parameters: string
    alwaysJson: 'true' | 'false'
}

export type LocalMeta = LegacyTransformationPluginMeta & {
    global: {
        ignoreCase: boolean
        setAsInitialUserProperties: boolean
        setAsUserProperties: boolean
        alwaysJson: boolean
        parameters: Set<string>
    }
    config: PluginConfig
}

function convertSearchParams(params: URLSearchParams): URLSearchParams {
    return new URLSearchParams([...params].map(([key, value]) => [key.toLowerCase(), value]) as [string, string][])
}

export const setupPlugin = (meta: LocalMeta): void => {
    const { global, config } = meta

    global.ignoreCase = config.ignoreCase === 'true'
    global.setAsInitialUserProperties = config.setAsInitialUserProperties === 'true'
    global.setAsUserProperties = config.setAsUserProperties === 'true'
    global.alwaysJson = config.alwaysJson === 'true'
    global.parameters = new Set(
        config.parameters ? config.parameters.split(',').map((parameter) => parameter.trim()) : null
    )
}

export const processEvent = (event: PluginEvent, meta: LocalMeta): PluginEvent => {
    if (event.properties?.$current_url) {
        const url = new URL(event.properties.$current_url)
        const params = meta.global.ignoreCase
            ? convertSearchParams(new URLSearchParams(url.searchParams))
            : new URLSearchParams(url.searchParams)

        for (const name of meta.global.parameters) {
            let value: string | Array<string> = ''

            if (meta.global.ignoreCase) {
                for (const key of params.keys()) {
                    if (key.toLowerCase() === name.toLowerCase()) {
                        value = params.getAll(key)
                    }
                }
            } else {
                value = params.getAll(name)
            }

            if (value.length > 0) {
                const key = `${meta.config.prefix}${name}${meta.config.suffix}`

                // if we've only got one, then just store the first string as a string
                // unless we want them all JSON-ified
                const storeValue = value.length === 1 && !meta.global.alwaysJson ? value[0] : JSON.stringify(value)

                event.properties[key] = storeValue
                if (meta.global.setAsUserProperties) {
                    event.properties.$set = event.properties.$set || {}
                    event.properties.$set[key] = storeValue
                }

                if (meta.global.setAsInitialUserProperties) {
                    event.properties.$set_once = event.properties.$set_once || {}
                    event.properties.$set_once[`initial_${key}`] = storeValue
                }
            }
        }
    }

    return event
}
