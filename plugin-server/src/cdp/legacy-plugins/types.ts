import { Meta, Plugin } from '@posthog/plugin-scaffold'
import fetch from 'node-fetch'

export type LegacyPlugin = {
    id: string
    name: string
    description: string
    onEvent: Plugin<any>['onEvent']
    setupPlugin: Plugin<any>['setupPlugin']
}

export type FetchType = typeof fetch

export type MetaWithFetch = Meta & {
    fetch: FetchType
}

export type PluginWithFetch = Plugin & {
    fetch: FetchType
}
