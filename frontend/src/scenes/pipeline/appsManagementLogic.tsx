import { actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import posthog from 'posthog-js'
import { canGloballyManagePlugins, canInstallPlugins } from 'scenes/plugins/access'
import { createDefaultPluginSource } from 'scenes/plugins/source/createDefaultPluginSource'
import { userLogic } from 'scenes/userLogic'

import { PluginInstallationType, PluginType } from '~/types'

import type { appsManagementLogicType } from './appsManagementLogicType'
import { loadPaginatedResults } from './utils'

const GLOBAL_PLUGINS = new Set([
    // frontend apps
    'https://github.com/PostHog/bug-report-app',
    'https://github.com/PostHog/early-access-features-app',
    'https://github.com/PostHog/notification-bar-app',
    'https://github.com/PostHog/pineapple-mode-app',
    // filtering apps
    'https://github.com/PostHog/downsampling-plugin',
    'https://github.com/PostHog/posthog-filter-out-plugin',
    // transformation apps
    'https://github.com/PostHog/language-url-splitter-app',
    'https://github.com/PostHog/posthog-app-url-parameters-to-event-properties',
    'https://github.com/PostHog/posthog-plugin-geoip',
    'https://github.com/PostHog/posthog-url-normalizer-plugin',
    'https://github.com/PostHog/property-filter-plugin',
    'https://github.com/PostHog/semver-flattener-plugin',
    'https://github.com/PostHog/taxonomy-plugin',
    'https://github.com/PostHog/timestamp-parser-plugin',
    'https://github.com/PostHog/user-agent-plugin',
    // export apps
    'https://github.com/PostHog/customerio-plugin',
    'https://github.com/PostHog/hubspot-plugin',
    'https://github.com/PostHog/pace-posthog-integration',
    'https://github.com/PostHog/posthog-avo-plugin',
    'https://github.com/PostHog/posthog-engage-so-plugin',
    'https://github.com/PostHog/posthog-intercom-plugin',
    'https://github.com/PostHog/posthog-laudspeaker-app',
    'https://github.com/PostHog/posthog-patterns-app',
    'https://github.com/PostHog/posthog-twilio-plugin',
    'https://github.com/PostHog/posthog-variance-plugin',
    'https://github.com/PostHog/rudderstack-posthog-plugin',
    'https://github.com/PostHog/salesforce-plugin',
    'https://github.com/PostHog/sendgrid-plugin',
    'https://github.com/posthog/posthog-plugin-replicator',
])

function capturePluginEvent(event: string, plugin: PluginType, type: PluginInstallationType): void {
    posthog.capture(event, {
        plugin_name: plugin.name,
        plugin_url: plugin.url?.startsWith('file:') ? 'file://masked-local-path' : plugin.url,
        plugin_tag: plugin.tag,
        plugin_installation_type: type,
    })
}

export const appsManagementLogic = kea<appsManagementLogicType>([
    path(['scenes', 'pipeline', 'appsManagementLogic']),
    connect({
        values: [userLogic, ['user']],
    }),
    actions({
        setPluginUrl: (pluginUrl: string) => ({ pluginUrl }),
        setLocalPluginPath: (localPluginPath: string) => ({ localPluginPath }),
        setSourcePluginName: (sourcePluginName: string) => ({ sourcePluginName }),
        uninstallPlugin: (id: number) => ({ id }),
        installPlugin: (pluginType: PluginInstallationType, url?: string) => ({ pluginType, url }),
        installPluginFromUrl: (url: string) => ({ url }),
        installSourcePlugin: (name: string) => ({ name }),
        installLocalPlugin: (path: string) => ({ path }),
        patchPlugin: (id: number, pluginChanges: Partial<PluginType> = {}) => ({ id, pluginChanges }),
    }),
    loaders(({ values }) => ({
        plugins: [
            {} as Record<number, PluginType>,
            {
                loadPlugins: async () => {
                    const results: PluginType[] = await loadPaginatedResults('api/organizations/@current/plugins')
                    const plugins: Record<string, PluginType> = {}
                    for (const plugin of results) {
                        plugins[plugin.id] = plugin
                    }
                    return plugins
                },
                installPlugin: async ({ pluginType, url }) => {
                    if (!values.canInstallPlugins) {
                        lemonToast.error("You don't have permission to install apps.")
                        return values.plugins
                    }
                    const payload: any = { plugin_type: pluginType }
                    if (url || pluginType === PluginInstallationType.Repository) {
                        payload.url = url
                    } else if (pluginType === PluginInstallationType.Custom) {
                        payload.url = values.pluginUrl
                    } else if (pluginType === PluginInstallationType.Local) {
                        payload.url = `file:${values.localPluginPath}`
                    } else if (pluginType === PluginInstallationType.Source) {
                        payload.name = values.sourcePluginName
                    } else {
                        lemonToast.error('Unsupported installation type.')
                        return values.plugins
                    }
                    const response: PluginType = await api.create('api/organizations/@current/plugins', payload)
                    if (pluginType === PluginInstallationType.Source) {
                        await api.update(`api/organizations/@current/plugins/${response.id}/update_source`, {
                            'plugin.json': createDefaultPluginSource(values.sourcePluginName)['plugin.json'],
                        })
                    }
                    capturePluginEvent(`plugin installed`, response, pluginType)
                    return { ...values.plugins, [response.id]: response }
                },
                uninstallPlugin: async ({ id }) => {
                    if (!values.canGloballyManagePlugins) {
                        lemonToast.error("You don't have permission to manage apps.")
                    }
                    await api.delete(`api/organizations/@current/plugins/${id}`)
                    capturePluginEvent(`plugin uninstalled`, values.plugins[id], values.plugins[id].plugin_type)
                    const { [id]: _discard, ...rest } = values.plugins
                    return rest
                },
                patchPlugin: async ({ id, pluginChanges }) => {
                    const response = await api.update(`api/organizations/@current/plugins/${id}`, pluginChanges)
                    return { ...values.plugins, [id]: response }
                },
            },
        ],
        unusedPlugins: [
            // used to know if plugin can be uninstalled
            [] as number[],
            {
                loadUnusedPlugins: async () => {
                    const results = await api.get('api/organizations/@current/plugins/unused')
                    return results
                },
            },
        ],
    })),
    reducers({
        installingPluginUrl: [
            null as string | null,
            {
                installPlugin: (_, { url }) => url || null,
                installPluginSuccess: () => null,
                installPluginFailure: () => null,
            },
        ],
        pluginUrl: [
            '',
            {
                setPluginUrl: (_, { pluginUrl }) => pluginUrl,
                installPluginSuccess: () => '',
            },
        ],
        localPluginPath: [
            '',
            {
                setLocalPluginPath: (_, { localPluginPath }) => localPluginPath,
                installPluginSuccess: () => '',
            },
        ],
        sourcePluginName: [
            '',
            {
                setSourcePluginName: (_, { sourcePluginName }) => sourcePluginName,
                installPluginSuccess: () => '',
            },
        ],
    }),
    selectors({
        canInstallPlugins: [(s) => [s.user], (user) => canInstallPlugins(user?.organization)],
        canGloballyManagePlugins: [(s) => [s.user], (user) => canGloballyManagePlugins(user?.organization)],
        globalPlugins: [(s) => [s.plugins], (plugins) => Object.values(plugins).filter((plugin) => plugin.is_global)],
        localPlugins: [(s) => [s.plugins], (plugins) => Object.values(plugins).filter((plugin) => !plugin.is_global)],
        missingGlobalPlugins: [
            (s) => [s.plugins],
            (plugins) => {
                const existingUrls = new Set(Object.values(plugins).map((p) => p.url))
                return Array.from(GLOBAL_PLUGINS).filter((url) => !existingUrls.has(url))
            },
        ],
        shouldBeGlobalPlugins: [
            (s) => [s.plugins],
            (plugins) => {
                return Object.values(plugins).filter(
                    (plugin) => plugin.url && GLOBAL_PLUGINS.has(plugin.url) && !plugin.is_global
                )
            },
        ],
        shouldNotBeGlobalPlugins: [
            (s) => [s.plugins],
            (plugins) => {
                return Object.values(plugins).filter(
                    (plugin) => !(plugin.url && GLOBAL_PLUGINS.has(plugin.url)) && plugin.is_global
                )
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadPlugins()
        actions.loadUnusedPlugins()
    }),
])
