import { Plugin } from '@posthog/plugin-scaffold'

export type LegacyPlugin = {
    id: string
    name: string
    description: string
    onEvent: Plugin<any>['onEvent']
    setupPlugin: Plugin<any>['setupPlugin']
}
