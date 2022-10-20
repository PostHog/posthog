import { PluginAttachment } from '@posthog/plugin-scaffold'

import { Hub, Plugin, PluginConfig, PluginConfigId, PluginId, StatelessVmMap, TeamId } from '../../types'
import { getPluginAttachmentRows, getPluginConfigRows, getPluginRows } from '../../utils/db/sql'
import { status } from '../../utils/status'
import { LazyPluginVM } from '../vm/lazy'
import { loadPlugin } from './loadPlugin'
import { teardownPlugins } from './teardown'

export async function setupPlugins(hub: Hub): Promise<void> {
    const { plugins, pluginConfigs, pluginConfigsPerTeam } = await loadPluginsFromDB(hub)
    const pluginVMLoadPromises: Array<Promise<any>> = []
    const statelessVms = {} as StatelessVmMap

    const timer = new Date()

    for (const [id, pluginConfig] of pluginConfigs) {
        const plugin = plugins.get(pluginConfig.plugin_id)
        const prevConfig = hub.pluginConfigs.get(id)
        const prevPlugin = prevConfig ? hub.plugins.get(pluginConfig.plugin_id) : null

        const pluginConfigChanged = !prevConfig || pluginConfig.updated_at !== prevConfig.updated_at
        const pluginChanged = plugin?.updated_at !== prevPlugin?.updated_at

        if (!pluginConfigChanged && !pluginChanged) {
            pluginConfig.vm = prevConfig.vm
        } else if (plugin?.is_stateless && statelessVms[plugin.id]) {
            pluginConfig.vm = statelessVms[plugin.id]
        } else {
            pluginConfig.vm = new LazyPluginVM(hub, pluginConfig)
            pluginVMLoadPromises.push(loadPlugin(hub, pluginConfig))

            if (prevConfig) {
                void teardownPlugins(hub, prevConfig)
            }

            if (plugin?.is_stateless) {
                statelessVms[plugin.id] = pluginConfig.vm
            }
        }
    }

    await Promise.all(pluginVMLoadPromises)
    hub.statsd?.timing('setup_plugins.success', timer)

    hub.plugins = plugins
    hub.pluginConfigs = pluginConfigs
    hub.pluginConfigsPerTeam = pluginConfigsPerTeam

    for (const teamId of hub.pluginConfigsPerTeam.keys()) {
        hub.pluginConfigsPerTeam.get(teamId)?.sort((a, b) => a.order - b.order)
    }

    // Only load the schedule in server that can process scheduled tasks, else the schedule won't be useful
    if (hub.capabilities.pluginScheduledTasks) {
        await loadSchedule(hub)
    }
}

async function loadPluginsFromDB(hub: Hub): Promise<Pick<Hub, 'plugins' | 'pluginConfigs' | 'pluginConfigsPerTeam'>> {
    const startTimer = new Date()
    const pluginRows = await getPluginRows(hub)
    const plugins = new Map<PluginId, Plugin>()

    for (const row of pluginRows) {
        plugins.set(row.id, row)
    }
    hub.statsd?.timing('load_plugins.plugins', startTimer)

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

    const pluginConfigTimer = new Date()
    const pluginConfigRows = await getPluginConfigRows(hub)

    const pluginConfigs = new Map<PluginConfigId, PluginConfig>()
    const pluginConfigsPerTeam = new Map<TeamId, PluginConfig[]>()

    for (const row of pluginConfigRows) {
        const plugin = plugins.get(row.plugin_id)
        if (!plugin) {
            continue
        }
        const pluginConfig: PluginConfig = {
            ...row,
            plugin: plugin,
            attachments: attachmentsPerConfig.get(row.id) || {},
            vm: null,
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

    hub.statsd?.timing('load_plugins.total', startTimer)

    return { plugins, pluginConfigs, pluginConfigsPerTeam }
}

export async function loadSchedule(server: Hub): Promise<void> {
    const timer = new Date()
    server.pluginSchedule = null

    // gather runEvery* tasks into a schedule
    const pluginSchedule: Record<string, PluginConfigId[]> = { runEveryMinute: [], runEveryHour: [], runEveryDay: [] }

    let count = 0

    for (const [id, pluginConfig] of server.pluginConfigs) {
        const tasks = (await pluginConfig.vm?.getScheduledTasks()) ?? {}
        for (const [taskName, task] of Object.entries(tasks)) {
            if (task && taskName in pluginSchedule) {
                pluginSchedule[taskName].push(id)
                count++
            }
        }
    }

    if (count > 0) {
        status.info('🔌', `Loaded ${count} scheduled tasks`)
    }

    server.pluginSchedule = pluginSchedule
    server.statsd?.timing('load_schedule.success', timer)
}
