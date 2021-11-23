import { PluginAttachment } from '@posthog/plugin-scaffold'

import { Hub, Plugin, PluginConfig, PluginConfigId, PluginId, PluginTaskType, TeamId } from '../../types'
import { getPluginAttachmentRows, getPluginConfigRows, getPluginRows } from '../../utils/db/sql'
import { status } from '../../utils/status'
import { LazyPluginVM } from '../vm/lazy'
import { loadPlugin } from './loadPlugin'
import { teardownPlugins } from './teardown'

export async function setupPlugins(server: Hub): Promise<void> {
    const { plugins, pluginConfigs, pluginConfigsPerTeam } = await loadPluginsFromDB(server)
    const pluginVMLoadPromises: Array<Promise<any>> = []
    for (const [id, pluginConfig] of pluginConfigs) {
        const plugin = plugins.get(pluginConfig.plugin_id)
        const prevConfig = server.pluginConfigs.get(id)
        const prevPlugin = prevConfig ? server.plugins.get(pluginConfig.plugin_id) : null

        if (
            prevConfig &&
            pluginConfig.updated_at === prevConfig.updated_at &&
            plugin?.updated_at == prevPlugin?.updated_at
        ) {
            pluginConfig.vm = prevConfig.vm
        } else {
            pluginConfig.vm = new LazyPluginVM()
            pluginVMLoadPromises.push(loadPlugin(server, pluginConfig))

            if (prevConfig) {
                void teardownPlugins(server, prevConfig)
            }
        }
    }

    await Promise.all(pluginVMLoadPromises)

    server.plugins = plugins
    server.pluginConfigs = pluginConfigs
    server.pluginConfigsPerTeam = pluginConfigsPerTeam

    for (const teamId of server.pluginConfigsPerTeam.keys()) {
        server.pluginConfigsPerTeam.get(teamId)?.sort((a, b) => a.order - b.order)
    }

    void loadSchedule(server)
}

async function loadPluginsFromDB(
    server: Hub
): Promise<Pick<Hub, 'plugins' | 'pluginConfigs' | 'pluginConfigsPerTeam'>> {
    const pluginRows = await getPluginRows(server)
    const plugins = new Map<PluginId, Plugin>()

    for (const row of pluginRows) {
        plugins.set(row.id, row)
    }

    const pluginAttachmentRows = await getPluginAttachmentRows(server)
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

    const pluginConfigRows = await getPluginConfigRows(server)

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

    return { plugins, pluginConfigs, pluginConfigsPerTeam }
}

export async function loadSchedule(server: Hub): Promise<void> {
    server.pluginSchedule = null

    // gather runEvery* tasks into a schedule
    const pluginSchedule: Record<string, PluginConfigId[]> = { runEveryMinute: [], runEveryHour: [], runEveryDay: [] }

    let count = 0

    for (const [id, pluginConfig] of server.pluginConfigs) {
        const tasks = (await pluginConfig.vm?.getTasks(PluginTaskType.Schedule)) ?? {}
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
}
