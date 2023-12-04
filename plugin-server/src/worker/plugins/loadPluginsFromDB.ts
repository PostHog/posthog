import { PluginAttachment } from '@posthog/plugin-scaffold'
import { Summary } from 'prom-client'

import { Hub, Plugin, PluginConfig, PluginConfigId, PluginId, PluginMethod, TeamId } from '../../types'
import { getPluginAttachmentRows, getPluginConfigRows, getPluginRows } from '../../utils/db/sql'

const loadPluginsMsSummary = new Summary({
    name: 'load_plugins_ms',
    help: 'Time to load plugins from DB',
    percentiles: [0.5, 0.9, 0.95, 0.99],
})
const loadPluginAttachmentsMsSummary = new Summary({
    name: 'load_plugin_attachments_ms',
    help: 'Time to load plugin attachments from DB',
    percentiles: [0.5, 0.9, 0.95, 0.99],
})
const loadPluginConfigsMsSummary = new Summary({
    name: 'load_plugin_configs_ms',
    help: 'Time to load plugin configs from DB',
    percentiles: [0.5, 0.9, 0.95, 0.99],
})
const loadPluginsTotalMsSummary = new Summary({
    name: 'load_plugins_total_ms',
    help: 'Time to load all plugin content from DB',
    percentiles: [0.5, 0.9, 0.95, 0.99],
})

export async function loadPluginsFromDB(
    hub: Hub
): Promise<Pick<Hub, 'plugins' | 'pluginConfigs' | 'pluginConfigsPerTeam'>> {
    const startTimer = new Date()
    const pluginRows = await getPluginRows(hub)
    const plugins = new Map<PluginId, Plugin>()

    for (const row of pluginRows) {
        plugins.set(row.id, row)
    }
    hub.statsd?.timing('load_plugins.plugins', startTimer)
    loadPluginsMsSummary.observe(new Date().getTime() - startTimer.getTime())

    const pluginAttachmentTimer = new Date()
    const pluginAttachmentRows = await getPluginAttachmentRows(hub)
    const attachmentsPerConfig = new Map<TeamId, Record<string, PluginAttachment>>()
    for (const row of pluginAttachmentRows) {
        let attachments = attachmentsPerConfig.get(row.plugin_config_id!)
        if (!attachments) {
            attachments = {}
            attachmentsPerConfig.set(row.plugin_config_id!, attachments)
        }
        attachments[row.key] = {
            content_type: row.content_type,
            file_name: row.file_name,
            contents: row.contents,
        }
    }
    hub.statsd?.timing('load_plugins.plugin_attachments', pluginAttachmentTimer)
    loadPluginAttachmentsMsSummary.observe(new Date().getTime() - pluginAttachmentTimer.getTime())

    const pluginConfigTimer = new Date()
    const pluginConfigRows = await getPluginConfigRows(hub)

    const pluginConfigs = new Map<PluginConfigId, PluginConfig>()
    const pluginConfigsPerTeam = new Map<TeamId, PluginConfig[]>()

    for (const row of pluginConfigRows) {
        const plugin = plugins.get(row.plugin_id)
        if (!plugin) {
            continue
        }
        let method = undefined
        if (plugin.capabilities?.methods) {
            const methods = plugin.capabilities.methods
            if (methods?.some((method) => [PluginMethod.onEvent.toString(), 'exportEvents'].includes(method))) {
                method = PluginMethod.onEvent
            } else if (methods?.some((method) => [PluginMethod.composeWebhook.toString()].includes(method))) {
                method = PluginMethod.composeWebhook
            }
        }
        const pluginConfig: PluginConfig = {
            ...row,
            plugin: plugin,
            attachments: attachmentsPerConfig.get(row.id) || {},
            vm: null,
            method,
        }
        pluginConfigs.set(row.id, pluginConfig)

        if (!row.team_id) {
            console.error(`🔴 PluginConfig(id=${row.id}) without team_id!`)
            continue
        }

        let teamConfigs = pluginConfigsPerTeam.get(row.team_id)
        if (!teamConfigs) {
            teamConfigs = []
            pluginConfigsPerTeam.set(row.team_id, teamConfigs)
        }
        teamConfigs.push(pluginConfig)
    }
    hub.statsd?.timing('load_plugins.plugin_configs', pluginConfigTimer)
    loadPluginConfigsMsSummary.observe(new Date().getTime() - pluginConfigTimer.getTime())

    hub.statsd?.timing('load_plugins.total', startTimer)
    loadPluginsTotalMsSummary.observe(new Date().getTime() - startTimer.getTime())

    return { plugins, pluginConfigs, pluginConfigsPerTeam }
}
