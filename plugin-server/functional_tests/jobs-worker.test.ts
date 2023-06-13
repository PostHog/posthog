import {
    createAndReloadPluginConfig,
    createOrganization,
    createPlugin,
    createTeam,
    disablePluginConfig,
    enablePluginConfig,
    fetchPluginLogEntries,
    getScheduledPluginJob,
    schedulePluginJob,
} from './api'
import { waitForExpect } from './expectations'

test.concurrent('graphile-worker does not run jobs for disabled plugins', async () => {
    // Here we are validating that if a Graphile task has been scheduled for a
    // pluginConfig that is disabled, then the task is not run. This is to avoid
    // spending resources unnecessarily.
    //
    // This should allow e.g. the ability to disable troublesome plugins e.g.
    // ones that have spawned too many tasks.
    const indexJs = `
        export const jobs = {
            runMeAsync: async (payload) => {
                console.info(JSON.stringify(payload))
            }
        }
    `

    const organizationId = await createOrganization()
    const plugin = await createPlugin({
        organization_id: organizationId,
        name: 'jobs plugin',
        plugin_type: 'source',
        is_global: false,
        source__index_ts: indexJs,
    })
    const teamId = await createTeam(organizationId)
    const pluginConfig = await createAndReloadPluginConfig(teamId, plugin.id)

    // Disable the plugin
    await disablePluginConfig(teamId, pluginConfig.id)

    // Schedule a task
    const job = await schedulePluginJob({
        teamId,
        pluginConfigId: pluginConfig.id,
        taskType: 'pluginJob',
        type: 'runMeAsync',
        payload: { identifier: 'should not run' },
    })

    // Wait for the task to run, it will become undefined
    await waitForExpect(async () => {
        const row = await getScheduledPluginJob(job.id)
        expect(row).not.toBeDefined()
    })

    // Re-enable the plugin and schedule a task, such that we can watch plugin
    // logs to see what ran.
    await enablePluginConfig(teamId, pluginConfig.id)

    // Schedule a task
    const job2 = await schedulePluginJob({
        teamId,
        pluginConfigId: pluginConfig.id,
        taskType: 'pluginJob',
        type: 'runMeAsync',
        payload: { identifier: 'should run' },
    })

    // Wait for the task to run, it will become undefined
    await waitForExpect(async () => {
        const row = await getScheduledPluginJob(job2.id)
        expect(row).not.toBeDefined()
    })

    // Check the logs to see what ran
    const logs = await waitForExpect(async () => {
        const logs = (await fetchPluginLogEntries(pluginConfig.id)).map((log) => log.message)
        expect(logs).toContain(JSON.stringify({ identifier: 'should run' }))
        return logs
    })

    expect(logs).toContain(JSON.stringify({ identifier: 'should not run' }))
})
