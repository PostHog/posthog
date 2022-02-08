import { DateTime } from 'luxon'
import { Pool } from 'pg'

import { Hub, LogLevel } from '../../src/types'
import { createHub } from '../../src/utils/db/hub'
import { EventsProcessor } from '../../src/worker/ingestion/process-event'
import { loadPlugin } from '../../src/worker/plugins/loadPlugin'
import { loadPluginsFromDB, loadSchedule } from '../../src/worker/plugins/setup'
import { teardownPlugins } from '../../src/worker/plugins/teardown'
import { LazyPluginVmManager } from '../../src/worker/vm/manager'
import { createTeam, resetTestDatabase } from '../../tests/helpers/sql'
import { StatelessVmMap } from './../../src/types'
import { UUIDT } from './../../src/utils/utils'
import { commonOrganizationId, plugin60, pluginConfig39 } from './../../tests/helpers/plugins'
import { getPluginAttachmentRows, getPluginConfigRows, getPluginRows } from './../../tests/helpers/sqlMock'
import { geoip } from './helpers/geoip'

jest.setTimeout(60000)

jest.mock('../../src/utils/db/sql')
jest.mock('../../src/utils/status')
jest.mock('../../src/utils/db/error')
jest.mock('../../src/worker/plugins/loadPlugin', () => {
    const { loadPlugin } = jest.requireActual('../../src/worker/plugins/loadPlugin')
    return { loadPlugin: jest.fn().mockImplementation(loadPlugin) }
})

const setupPluginsMock = async (server: Hub, useMultipleVms = false): Promise<void> => {
    const { plugins, pluginConfigs, pluginConfigsPerTeam } = await loadPluginsFromDB(server)
    const pluginVMLoadPromises: Array<Promise<any>> = []
    const statelessVms = {} as StatelessVmMap

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
        } else if (plugin?.is_stateless && statelessVms[plugin.id]) {
            pluginConfig.vm = statelessVms[plugin.id]
        } else {
            pluginConfig.vm = new LazyPluginVmManager(server, useMultipleVms)
            pluginVMLoadPromises.push(loadPlugin(server, pluginConfig))

            if (prevConfig) {
                void teardownPlugins(server, prevConfig)
            }

            if (plugin?.is_stateless) {
                statelessVms[plugin.id] = pluginConfig.vm
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

describe('Stateless VM Architecture', () => {
    let eventsProcessor: EventsProcessor
    const now = DateTime.utc()
    let hub: Hub
    let closeHub: () => Promise<void>

    beforeEach(async () => {
        ;[hub, closeHub] = await createHub({ LOG_LEVEL: LogLevel.Log })
        console.warn = jest.fn() as any
        await resetTestDatabase()
        eventsProcessor = new EventsProcessor(hub)

        const db = new Pool({ connectionString: hub.DATABASE_URL! })

        try {
            await createTeam(db, 1, commonOrganizationId)
            await createTeam(db, 3, commonOrganizationId)
            await createTeam(db, 4, commonOrganizationId)
            await createTeam(db, 5, commonOrganizationId)
        } catch {}
    })

    afterEach(async () => {
        await closeHub()
    })

    test('Multiple VMs', async () => {
        const plugin = { ...plugin60, indexJs: geoip, is_stateless: true }
        getPluginRows.mockReturnValueOnce([plugin])
        getPluginAttachmentRows.mockReturnValueOnce([])

        getPluginConfigRows.mockReturnValueOnce([
            { ...pluginConfig39, team_id: 1, id: 39 },
            { ...pluginConfig39, team_id: 2, id: 40 },
            { ...pluginConfig39, team_id: 3, id: 41 },
            { ...pluginConfig39, team_id: 4, id: 42 },
            { ...pluginConfig39, team_id: 5, id: 43 },
        ])

        await setupPluginsMock(hub)

        const processEventFunctions = []

        for (let i = 39; i < 44; ++i) {
            const processEvent = await hub.pluginConfigs.get(i)!.vm!.getVm().getProcessEvent()
            processEventFunctions.push(processEvent)
        }

        const timerStart = new Date().getTime()
        const promises = []
        for (let i = 0; i < 100000; ++i) {
            const func = processEventFunctions[i % 5]
            if (func) {
                promises.push(
                    func({
                        distinct_id: 'hello',
                        ip: '127.0.0.1',
                        team_id: (i % 5) + 1,
                        event: 'some event',
                        properties: {},
                        uuid: new UUIDT().toString(),
                        now: now.toISO(),
                        site_url: 'mywebsite',
                    })
                )
            }
        }

        await Promise.all(promises)

        const timerEnd = new Date().getTime()

        console.log('Multiple VMs timer:', timerEnd - timerStart)
    })

    test('1 VM overall', async () => {
        const plugin = { ...plugin60, indexJs: geoip, is_stateless: true }
        getPluginRows.mockReturnValueOnce([plugin])
        getPluginAttachmentRows.mockReturnValueOnce([])

        getPluginConfigRows.mockReturnValueOnce([
            { ...pluginConfig39, team_id: 1, id: 39 },
            { ...pluginConfig39, team_id: 2, id: 40 },
            { ...pluginConfig39, team_id: 3, id: 41 },
            { ...pluginConfig39, team_id: 4, id: 42 },
            { ...pluginConfig39, team_id: 5, id: 43 },
        ])

        await setupPluginsMock(hub)

        const processEventFunctions = []

        for (let i = 39; i < 44; ++i) {
            const processEvent = await hub.pluginConfigs.get(i)!.vm!.getVm().getProcessEvent()
            processEventFunctions.push(processEvent)
        }

        const timerStart = new Date().getTime()
        const promises = []
        for (let i = 0; i < 100000; ++i) {
            const func = processEventFunctions[i % 5]
            if (func) {
                promises.push(
                    func({
                        distinct_id: 'hello',
                        ip: '127.0.0.1',
                        team_id: (i % 5) + 1,
                        event: 'some event',
                        properties: {},
                        uuid: new UUIDT().toString(),
                        now: now.toISO(),
                        site_url: 'mywebsite',
                    })
                )
            }
        }

        await Promise.all(promises)

        const timerEnd = new Date().getTime()

        console.log('1 VM timer:', timerEnd - timerStart)
    })
})
