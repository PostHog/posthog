import { PluginEvent } from '@posthog/plugin-scaffold/src/types'

import { Hub, LogLevel } from '../../src/types'
import { processError } from '../../src/utils/db/error'
import { createHub } from '../../src/utils/db/hub'
import { delay, IllegalOperationError } from '../../src/utils/utils'
import { loadPlugin } from '../../src/worker/plugins/loadPlugin'
import { getPluginConfig, runProcessEvent } from '../../src/worker/plugins/run'
import {
    commonOrganizationId,
    mockPluginSourceCode,
    mockPluginTempFolder,
    mockPluginWithSourceFiles,
    plugin60,
    pluginAttachment1,
    pluginConfig39,
} from '../helpers/plugins'
import {
    createOrganization,
    createPlugin,
    createPluginAttachment,
    createPluginConfig,
    createTeam,
    resetTestDatabase,
} from '../helpers/sql'
import { getPluginAttachmentRows, getPluginConfigRows, getPluginRows, setPluginCapabilities } from '../helpers/sqlMock'

jest.mock('../../src/utils/db/sql')
jest.mock('../../src/utils/status')
jest.mock('../../src/utils/db/error')
jest.mock('../../src/worker/plugins/loadPlugin', () => {
    const { loadPlugin } = jest.requireActual('../../src/worker/plugins/loadPlugin')
    return { loadPlugin: jest.fn().mockImplementation(loadPlugin) }
})
jest.setTimeout(20_000)

describe('plugins', () => {
    let hub: Hub
    let closeHub: () => Promise<void>

    beforeEach(async () => {
        ;[hub, closeHub] = await createHub({ LOG_LEVEL: LogLevel.Log })
        console.warn = jest.fn() as any
        await resetTestDatabase()
    })

    afterEach(async () => {
        await closeHub()
    })

    test('setupPlugins and runProcessEvent', async () => {
        const organizationId = await createOrganization(hub.postgres)
        const teamId = await createTeam(hub.postgres, organizationId)
        const { id: _, ...pluginData } = plugin60
        const plugin = await createPlugin(hub.postgres, { ...pluginData, organization_id: organizationId })
        const { id: __, ...pluginConfigData } = pluginConfig39
        const pluginConfigRow = await createPluginConfig(hub.postgres, {
            ...pluginConfigData,
            plugin_id: plugin.id,
            team_id: teamId,
        })
        const { id: ___, ...pluginAttachmentData } = pluginAttachment1
        await createPluginAttachment(hub.postgres, {
            ...pluginAttachmentData,
            plugin_config_id: pluginConfigRow.id,
            team_id: teamId,
        })

        const pluginConfig = (await getPluginConfig(hub, pluginConfigRow.id))!

        expect(pluginConfig.plugin).toEqual(
            expect.objectContaining({
                capabilities: { jobs: [], scheduled_tasks: [], methods: ['processEvent'] },
            })
        )

        expect(pluginConfig.attachments).toEqual({
            maxmindMmdb: {
                content_type: pluginAttachment1.content_type,
                file_name: pluginAttachment1.file_name,
                contents: pluginAttachment1.contents,
            },
        })
        expect(pluginConfig.vm).toBeDefined()
        const vm = await pluginConfig.vm!.resolveInternalVm
        expect(Object.keys(vm!.methods).sort()).toEqual([
            'exportEvents',
            'getSettings',
            'onEvent',
            'onSnapshot',
            'processEvent',
            'setupPlugin',
            'teardownPlugin',
        ])

        // async loading of capabilities
        expect(setPluginCapabilities).toHaveBeenCalled()

        const processEvent = vm!.methods['processEvent']!
        const event = { event: '$test', properties: {}, team_id: teamId } as PluginEvent
        await processEvent(event)

        expect(event.properties!['processed']).toEqual(true)

        event.properties!['processed'] = false

        const returnedEvent = await runProcessEvent(hub, event)
        expect(event.properties!['processed']).toEqual(true)
        expect(returnedEvent!.properties!['processed']).toEqual(true)
    })

    test('stateless plugins', async () => {
        const organizationId = await createOrganization(hub.postgres)
        const teamId = await createTeam(hub.postgres, organizationId)
        const otherTeamId = await createTeam(hub.postgres, organizationId)
        const { id: _, ...pluginData } = plugin60
        const plugin = await createPlugin(hub.postgres, {
            ...pluginData,
            organization_id: organizationId,
            is_stateless: true,
        })
        const { id: __, ...pluginConfigData } = pluginConfig39
        const pluginConfigRow = await createPluginConfig(hub.postgres, {
            ...pluginConfigData,
            plugin_id: plugin.id,
            team_id: teamId,
        })
        const otherPluginConfigRow = await createPluginConfig(hub.postgres, {
            ...pluginConfigData,
            plugin_id: plugin.id,
            team_id: otherTeamId,
        })

        const pluginConfigTeam1 = (await getPluginConfig(hub, pluginConfigRow.id))!
        const pluginConfigTeam2 = (await getPluginConfig(hub, otherPluginConfigRow.id))!

        expect(pluginConfigTeam1.plugin).toEqual(pluginConfigTeam2.plugin)

        expect(pluginConfigTeam1.vm).toBeDefined()
        expect(pluginConfigTeam2.vm).toBeDefined()

        expect(pluginConfigTeam1.vm).toEqual(pluginConfigTeam2.vm)
    })

    test('plugin returns null', async () => {
        const organizationId = await createOrganization(hub.postgres)
        const teamId = await createTeam(hub.postgres, organizationId)
        const { id: _, ...pluginData } = plugin60
        const plugin = await createPlugin(hub.postgres, {
            ...pluginData,
            organization_id: organizationId,
            source__index_ts: 'function processEvent (event, meta) { return null }',
        })
        const { id: __, ...pluginConfigData } = pluginConfig39
        await createPluginConfig(hub.postgres, { ...pluginConfigData, plugin_id: plugin.id, team_id: teamId })

        const event = { event: '$test', properties: {}, team_id: teamId } as PluginEvent
        const returnedEvent = await runProcessEvent(hub, event)

        expect(returnedEvent).toEqual(null)
    })

    test('plugin meta has what it should have', async () => {
        const organizationId = await createOrganization(hub.postgres)
        const teamId = await createTeam(hub.postgres, organizationId)
        const { id: _, ...pluginData } = plugin60
        const plugin = await createPlugin(hub.postgres, {
            ...pluginData,
            organization_id: organizationId,
            source__index_ts: `
        function setupPlugin (meta) { meta.global.key = 'value' }
        function processEvent (event, meta) { event.properties=meta; return event }
    `,
        })
        const { id: __, ...pluginConfigData } = pluginConfig39
        const pluginConfigRow = await createPluginConfig(hub.postgres, {
            ...pluginConfigData,
            plugin_id: plugin.id,
            team_id: teamId,
        })
        const { id: ___, ...pluginAttachmentData } = pluginAttachment1
        await createPluginAttachment(hub.postgres, {
            ...pluginAttachmentData,
            plugin_config_id: pluginConfigRow.id,
            team_id: teamId,
        })

        const event = { event: '$test', properties: {}, team_id: teamId } as PluginEvent
        const returnedEvent = await runProcessEvent(hub, event)

        expect(Object.keys(returnedEvent!.properties!).sort()).toEqual([
            '$plugins_deferred',
            '$plugins_failed',
            '$plugins_succeeded',
            'attachments',
            'cache',
            'config',
            'geoip',
            'global',
            'jobs',
            'storage',
            'utils',
        ])
        expect(returnedEvent!.properties!['attachments']).toEqual({
            maxmindMmdb: {
                content_type: 'application/octet-stream',
                contents: Buffer.from('test'),
                file_name: 'test.txt',
            },
        })
        expect(returnedEvent!.properties!['config']).toEqual({ localhostIP: '94.224.212.175' })
        expect(returnedEvent!.properties!['global']).toEqual({ key: 'value' })
    })

    test('source files plugin with broken index.js does not do much', async () => {
        // silence some spam
        console.log = jest.fn()
        console.error = jest.fn()

        const organizationId = await createOrganization(hub.postgres)
        const teamId = await createTeam(hub.postgres, organizationId)
        const { id: _, ...pluginData } = plugin60
        const plugin = await createPlugin(hub.postgres, {
            ...pluginData,
            organization_id: organizationId,
            source__index_ts: `
                function setupPlugin (met
            `,
        })
        const { id: __, ...pluginConfigData } = pluginConfig39
        const pluginConfigRow = await createPluginConfig(hub.postgres, {
            ...pluginConfigData,
            plugin_id: plugin.id,
            team_id: teamId,
        })

        const pluginConfig = (await getPluginConfig(hub, pluginConfigRow.id))!

        pluginConfig.vm!.totalInitAttemptsCounter = 20 // prevent more retries
        await delay(4000) // processError is called at end of retries
        expect(await pluginConfig.vm!.getScheduledTasks()).toEqual({})

        const event = { event: '$test', properties: {}, team_id: teamId } as PluginEvent
        const returnedEvent = await runProcessEvent(hub, { ...event })
        expect(returnedEvent).toEqual(event)

        expect(processError).toHaveBeenCalledWith(hub, pluginConfig, expect.any(SyntaxError))
        const error = jest.mocked(processError).mock.calls[0][2]! as Error
        expect(error.message).toContain(': Unexpected token, expected ","')
    })

    test('local plugin with broken index.js does not do much', async () => {
        // silence some spam
        console.log = jest.fn()
        console.error = jest.fn()

        const [localPluginData, unlink] = mockPluginTempFolder(`function setupPlugin (met`)

        const organizationId = await createOrganization(hub.postgres)
        const teamId = await createTeam(hub.postgres, organizationId)
        const { id: _, ...pluginData } = localPluginData
        const plugin = await createPlugin(hub.postgres, {
            ...pluginData,
            organization_id: organizationId,
        })
        const { id: __, ...pluginConfigData } = pluginConfig39
        const pluginConfigRow = await createPluginConfig(hub.postgres, {
            ...pluginConfigData,
            plugin_id: plugin.id,
            team_id: teamId,
        })

        const pluginConfig = (await getPluginConfig(hub, pluginConfigRow.id))!

        pluginConfig.vm!.totalInitAttemptsCounter = 20 // prevent more retries
        await delay(4000) // processError is called at end of retries
        expect(await pluginConfig.vm!.getScheduledTasks()).toEqual({})

        const event = { event: '$test', properties: {}, team_id: teamId } as PluginEvent
        const returnedEvent = await runProcessEvent(hub, { ...event })
        expect(returnedEvent).toEqual(event)

        expect(processError).toHaveBeenCalledWith(hub, pluginConfig, expect.any(SyntaxError))
        const error = jest.mocked(processError).mock.calls[0][2]! as Error
        expect(error.message).toContain(': Unexpected token, expected ","')

        unlink()
    })

    test('plugin changing event.team_id throws error', async () => {
        const localPluginData = mockPluginWithSourceFiles(`
            function processEvent (event, meta) {
                event.team_id = 400
                return event
            }
        `)

        const organizationId = await createOrganization(hub.postgres)
        const teamId = await createTeam(hub.postgres, organizationId)
        const { id: _, ...pluginData } = localPluginData
        const plugin = await createPlugin(hub.postgres, {
            ...pluginData,
            organization_id: organizationId,
        })
        const { id: __, ...pluginConfigData } = pluginConfig39
        const pluginConfigRow = await createPluginConfig(hub.postgres, {
            ...pluginConfigData,
            plugin_id: plugin.id,
            team_id: teamId,
        })

        const pluginConfig = (await getPluginConfig(hub, pluginConfigRow.id))!

        const event = { event: '$test', properties: {}, team_id: teamId } as PluginEvent
        const returnedEvent = await runProcessEvent(hub, event)

        const expectedReturnedEvent = {
            event: '$test',
            properties: {
                $plugins_failed: [`test-maxmind-plugin (${pluginConfig.id})`],
                $plugins_succeeded: [],
                $plugins_deferred: [],
            },
            team_id: teamId,
        }
        expect(returnedEvent).toEqual(expectedReturnedEvent)

        expect(processError).toHaveBeenCalledWith(
            hub,
            pluginConfig,
            new IllegalOperationError('Plugin tried to change event.team_id'),
            expectedReturnedEvent
        )
    })

    test('plugin throwing error does not prevent ingestion and failure is noted in event', async () => {
        // silence some spam
        console.log = jest.fn()
        console.error = jest.fn()

        const localPluginData = mockPluginWithSourceFiles(`
            function processEvent (event) {
                throw new Error('I always fail!')
            }
        `)

        const organizationId = await createOrganization(hub.postgres)
        const teamId = await createTeam(hub.postgres, organizationId)
        const { id: _, ...pluginData } = localPluginData
        const plugin = await createPlugin(hub.postgres, {
            ...pluginData,
            organization_id: organizationId,
        })
        const { id: __, ...pluginConfigData } = pluginConfig39
        const pluginConfigRow = await createPluginConfig(hub.postgres, {
            ...pluginConfigData,
            plugin_id: plugin.id,
            team_id: teamId,
        })

        const pluginConfig = (await getPluginConfig(hub, pluginConfigRow.id))!

        expect(await pluginConfig!.vm!.getScheduledTasks()).toEqual({})

        const event = { event: '$test', properties: {}, team_id: teamId } as PluginEvent
        const returnedEvent = await runProcessEvent(hub, { ...event })

        const expectedReturnEvent = {
            ...event,
            properties: {
                $plugins_failed: [`test-maxmind-plugin (${pluginConfig.id})`],
                $plugins_succeeded: [],
                $plugins_deferred: [],
            },
        }
        expect(returnedEvent).toEqual(expectedReturnEvent)
    })

    test('events have property $plugins_succeeded set to the plugins that succeeded', async () => {
        // silence some spam
        console.log = jest.fn()
        console.error = jest.fn()

        const localPluginData = mockPluginWithSourceFiles(`
            function processEvent (event) {
                return event
            }
        `)

        const organizationId = await createOrganization(hub.postgres)
        const teamId = await createTeam(hub.postgres, organizationId)
        const { id: _, ...pluginData } = localPluginData
        const plugin = await createPlugin(hub.postgres, {
            ...pluginData,
            organization_id: organizationId,
        })
        const { id: __, ...pluginConfigData } = pluginConfig39
        const pluginConfigRow = await createPluginConfig(hub.postgres, {
            ...pluginConfigData,
            plugin_id: plugin.id,
            team_id: teamId,
        })

        const pluginConfig = (await getPluginConfig(hub, pluginConfigRow.id))!

        expect(await pluginConfig!.vm!.getScheduledTasks()).toEqual({})

        const event = { event: '$test', properties: {}, team_id: teamId } as PluginEvent
        const returnedEvent = await runProcessEvent(hub, { ...event })

        const expectedReturnEvent = {
            ...event,
            properties: {
                $plugins_failed: [],
                $plugins_succeeded: [`test-maxmind-plugin (${pluginConfig.id})`],
                $plugins_deferred: [],
            },
        }
        expect(returnedEvent).toEqual(expectedReturnEvent)
    })

    test('events have property $plugins_deferred set to the plugins that run after processEvent', async () => {
        // silence some spam
        console.log = jest.fn()
        console.error = jest.fn()

        const localPluginData = mockPluginWithSourceFiles(`
            function onEvent (event) {
                return event
            }
        `)

        const organizationId = await createOrganization(hub.postgres)
        const teamId = await createTeam(hub.postgres, organizationId)
        const { id: _, ...pluginData } = localPluginData
        const plugin = await createPlugin(hub.postgres, {
            ...pluginData,
            organization_id: organizationId,
        })
        const { id: __, ...pluginConfigData } = pluginConfig39
        const pluginConfigRow = await createPluginConfig(hub.postgres, {
            ...pluginConfigData,
            plugin_id: plugin.id,
            team_id: teamId,
        })

        const pluginConfig = (await getPluginConfig(hub, pluginConfigRow.id))!

        expect(await pluginConfig!.vm!.getScheduledTasks()).toEqual({})

        const event = { event: '$test', properties: {}, team_id: teamId } as PluginEvent
        const returnedEvent = await runProcessEvent(hub, { ...event })

        const expectedReturnEvent = {
            ...event,
            properties: {
                $plugins_failed: [],
                $plugins_succeeded: [],
                $plugins_deferred: [`test-maxmind-plugin (${pluginConfig.id})`],
            },
        }
        expect(returnedEvent).toEqual(expectedReturnEvent)
    })

    test('source files plugin with broken plugin.json does not do much', async () => {
        // silence some spam
        console.log = jest.fn()
        console.error = jest.fn()

        const localPluginData = mockPluginWithSourceFiles(
            `function processEvent (event, meta) { event.properties.processed = true; return event }`,
            '{ broken: "plugin.json" -=- '
        )

        const organizationId = await createOrganization(hub.postgres)
        const teamId = await createTeam(hub.postgres, organizationId)
        const { id: _, ...pluginData } = localPluginData
        const plugin = await createPlugin(hub.postgres, {
            ...pluginData,
            organization_id: organizationId,
        })
        const { id: __, ...pluginConfigData } = pluginConfig39
        const pluginConfigRow = await createPluginConfig(hub.postgres, {
            ...pluginConfigData,
            plugin_id: plugin.id,
            team_id: teamId,
        })

        const pluginConfig = (await getPluginConfig(hub, pluginConfigRow.id))!

        expect(await pluginConfig!.vm!.getScheduledTasks()).toEqual({})

        expect(processError).toHaveBeenCalledWith(
            hub,
            pluginConfig!,
            `Could not load "plugin.json" for plugin test-maxmind-plugin ID ${plugin.id} (organization ID ${organizationId})`
        )
    })

    test('local plugin with broken plugin.json does not do much', async () => {
        // silence some spam
        console.log = jest.fn()
        console.error = jest.fn()

        const [localPluginData, unlink] = mockPluginTempFolder(
            `function processEvent (event, meta) { event.properties.processed = true; return event }`,
            '{ broken: "plugin.json" -=- '
        )

        const organizationId = await createOrganization(hub.postgres)
        const teamId = await createTeam(hub.postgres, organizationId)
        const { id: _, ...pluginData } = localPluginData
        const plugin = await createPlugin(hub.postgres, {
            ...pluginData,
            organization_id: organizationId,
        })
        const { id: __, ...pluginConfigData } = pluginConfig39
        const pluginConfigRow = await createPluginConfig(hub.postgres, {
            ...pluginConfigData,
            plugin_id: plugin.id,
            team_id: teamId,
        })

        const pluginConfig = (await getPluginConfig(hub, pluginConfigRow.id))!

        expect(await pluginConfig!.vm!.getScheduledTasks()).toEqual({})
        expect(processError).toHaveBeenCalledWith(
            hub,
            pluginConfig!,
            expect.stringContaining('Could not load "plugin.json" for plugin ')
        )

        unlink()
    })

    test('plugin with http urls must have source files', async () => {
        // silence some spam
        console.log = jest.fn()
        console.error = jest.fn()

        const organizationId = await createOrganization(hub.postgres)
        const teamId = await createTeam(hub.postgres, organizationId)
        const { id: _, ...pluginData } = plugin60
        const plugin = await createPlugin(hub.postgres, {
            ...pluginData,
            organization_id: organizationId,
        })
        const { id: __, ...pluginConfigData } = pluginConfig39
        const pluginConfigRow = await createPluginConfig(hub.postgres, {
            ...pluginConfigData,
            plugin_id: plugin.id,
            team_id: teamId,
        })

        const pluginConfig = (await getPluginConfig(hub, pluginConfigRow.id))!

        expect(pluginConfig!.plugin!.url).toContain('https://')
        expect(processError).toHaveBeenCalledWith(
            hub,
            pluginConfig,
            `Could not load source code for plugin test-maxmind-plugin ID 60 (organization ID ${commonOrganizationId}). Tried: index.js`
        )
        expect(await pluginConfig!.vm!.getScheduledTasks()).toEqual({})
    })

    test('plugin config order', async () => {
        const organizationId = await createOrganization(hub.postgres)
        const teamId = await createTeam(hub.postgres, organizationId)
        const { id: _, ...pluginData } = plugin60
        const plugin1 = await createPlugin(hub.postgres, {
            ...pluginData,
            organization_id: organizationId,
            source__index_ts: `function processEvent(event) {
                event.properties.plugins = [...(event.properties.plugins || []), 60]
                return event
              }`,
        })

        const plugin2 = await createPlugin(hub.postgres, {
            ...pluginData,
            organization_id: organizationId,
            source__index_ts: `function processEvent(event) {
                event.properties.plugins = [...(event.properties.plugins || []), 61]
                return event
              }`,
        })

        const plugin3 = await createPlugin(hub.postgres, {
            ...pluginData,
            organization_id: organizationId,
            source__index_ts: `function processEvent(event) {
                event.properties.plugins = [...(event.properties.plugins || []), 62]
                return event
              }`,
        })

        const { id: __, ...pluginConfigData } = pluginConfig39

        await createPluginConfig(hub.postgres, {
            ...pluginConfigData,
            plugin_id: plugin1.id,
            team_id: teamId,
            order: 2,
        })
        await createPluginConfig(hub.postgres, {
            ...pluginConfigData,
            plugin_id: plugin2.id,
            team_id: teamId,
            order: 1,
        })
        await createPluginConfig(hub.postgres, {
            ...pluginConfigData,
            plugin_id: plugin3.id,
            team_id: teamId,
            order: 3,
        })

        const event = { event: '$test', properties: {}, team_id: teamId } as PluginEvent

        const returnedEvent1 = await runProcessEvent(hub, { ...event, properties: { ...event.properties } })
        expect(returnedEvent1!.properties!.plugins).toEqual([61, 60, 62])

        const returnedEvent2 = await runProcessEvent(hub, { ...event, properties: { ...event.properties } })
        expect(returnedEvent2!.properties!.plugins).toEqual([61, 60, 62])
    })

    test('plugin with source files loads capabilities', async () => {
        const organizationId = await createOrganization(hub.postgres)
        const teamId = await createTeam(hub.postgres, organizationId)
        const { id: _, ...pluginData } = mockPluginWithSourceFiles(`
            function setupPlugin (meta) { meta.global.key = 'value' }
            function processEvent (event, meta) { event.properties={"x": 1}; return event }
        `)
        const plugin = await createPlugin(hub.postgres, {
            ...pluginData,
            organization_id: organizationId,
        })
        const { id: __, ...pluginConfigData } = pluginConfig39
        const pluginConfigRow = await createPluginConfig(hub.postgres, {
            ...pluginConfigData,
            plugin_id: plugin.id,
            team_id: teamId,
        })

        const pluginConfig = (await getPluginConfig(hub, pluginConfigRow.id))!

        await pluginConfig.vm?.resolveInternalVm
        // async loading of capabilities

        expect(pluginConfig.plugin!.capabilities!.methods!.sort()).toEqual(['processEvent', 'setupPlugin'])
        expect(pluginConfig.plugin!.capabilities!.jobs).toHaveLength(0)
        expect(pluginConfig.plugin!.capabilities!.scheduled_tasks).toHaveLength(0)
    })

    test('plugin with source files loads all capabilities, no random caps', async () => {
        const organizationId = await createOrganization(hub.postgres)
        const teamId = await createTeam(hub.postgres, organizationId)
        const { id: _, ...pluginData } = mockPluginWithSourceFiles(`
            export function processEvent (event, meta) { event.properties={"x": 1}; return event }
            export function randomFunction (event, meta) { return event}
            export function onEvent (event, meta) { return event }

            export function runEveryHour(meta) {console.log('1')}

            export const jobs = {
                x: (event, meta) => console.log(event)
            }
        `)
        const plugin = await createPlugin(hub.postgres, {
            ...pluginData,
            organization_id: organizationId,
        })
        const { id: __, ...pluginConfigData } = pluginConfig39
        const pluginConfigRow = await createPluginConfig(hub.postgres, {
            ...pluginConfigData,
            plugin_id: plugin.id,
            team_id: teamId,
        })

        const pluginConfig = (await getPluginConfig(hub, pluginConfigRow.id))!

        await pluginConfig.vm?.resolveInternalVm
        // async loading of capabilities

        expect(pluginConfig.plugin!.capabilities!.methods!.sort()).toEqual(['onEvent', 'processEvent'])
        expect(pluginConfig.plugin!.capabilities!.jobs).toEqual(['x'])
        expect(pluginConfig.plugin!.capabilities!.scheduled_tasks).toEqual(['runEveryHour'])
    })

    test('plugin with source file loads capabilities', async () => {
        const [localPluginData, unlink] = mockPluginTempFolder(`
            function processEvent (event, meta) { event.properties={"x": 1}; return event }
            function randomFunction (event, meta) { return event}
            function onEvent (event, meta) { return event }
        `)

        const organizationId = await createOrganization(hub.postgres)
        const teamId = await createTeam(hub.postgres, organizationId)
        const { id: _, ...pluginData } = localPluginData
        const plugin = await createPlugin(hub.postgres, {
            ...pluginData,
            organization_id: organizationId,
        })
        const { id: __, ...pluginConfigData } = pluginConfig39
        const pluginConfigRow = await createPluginConfig(hub.postgres, {
            ...pluginConfigData,
            plugin_id: plugin.id,
            team_id: teamId,
        })

        const pluginConfig = (await getPluginConfig(hub, pluginConfigRow.id))!

        await pluginConfig.vm?.resolveInternalVm
        // async loading of capabilities

        expect(pluginConfig.plugin!.capabilities!.methods!.sort()).toEqual(['onEvent', 'processEvent'])
        expect(pluginConfig.plugin!.capabilities!.jobs).toEqual([])
        expect(pluginConfig.plugin!.capabilities!.scheduled_tasks).toEqual([])

        unlink()
    })

    test('plugin with source code loads capabilities', async () => {
        const localPluginData = {
            ...mockPluginSourceCode(),
            source__index_ts: `
        function processEvent (event, meta) { event.properties={"x": 1}; return event }
        function randomFunction (event, meta) { return event}
        function onSnapshot (event, meta) { return event }`,
        }

        const organizationId = await createOrganization(hub.postgres)
        const teamId = await createTeam(hub.postgres, organizationId)
        const { id: _, ...pluginData } = localPluginData
        const plugin = await createPlugin(hub.postgres, {
            ...pluginData,
            organization_id: organizationId,
        })
        const { id: __, ...pluginConfigData } = pluginConfig39
        const pluginConfigRow = await createPluginConfig(hub.postgres, {
            ...pluginConfigData,
            plugin_id: plugin.id,
            team_id: teamId,
        })

        const pluginConfig = (await getPluginConfig(hub, pluginConfigRow.id))!

        await pluginConfig.vm?.resolveInternalVm
        // async loading of capabilities

        expect(pluginConfig.plugin!.capabilities!.methods!.sort()).toEqual(['onSnapshot', 'processEvent'])
        expect(pluginConfig.plugin!.capabilities!.jobs).toEqual([])
        expect(pluginConfig.plugin!.capabilities!.scheduled_tasks).toEqual([])
    })

    test('plugin with frontend source transpiles it', async () => {
        const localPluginData = { ...mockPluginSourceCode(), source__frontend_tsx: `export const scene = {}` }

        const organizationId = await createOrganization(hub.postgres)
        const teamId = await createTeam(hub.postgres, organizationId)
        const { id: _, ...pluginData } = localPluginData
        const plugin = await createPlugin(hub.postgres, {
            ...pluginData,
            organization_id: organizationId,
        })
        const { id: __, ...pluginConfigData } = pluginConfig39
        await createPluginConfig(hub.postgres, { ...pluginConfigData, plugin_id: plugin.id, team_id: teamId })

        const {
            rows: [{ transpiled }],
        } = await hub.db.postgresQuery(
            `SELECT transpiled FROM posthog_pluginsourcefile WHERE plugin_id = $1 AND filename = $2`,
            [plugin.id, 'frontend.tsx'],
            ''
        )
        expect(transpiled).toEqual(`"use strict";
export function getFrontendApp (require) { let exports = {}; "use strict";

Object.defineProperty(exports, "__esModule", {
  value: true
});
exports.scene = void 0;
var scene = {};
exports.scene = scene;; return exports; }`)
    })

    test('plugin with frontend source with error', async () => {
        getPluginRows.mockReturnValueOnce([
            { ...mockPluginSourceCode(), source__frontend_tsx: `export const scene = {}/` },
        ])
        getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
        getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])
        await setupPlugins(hub)
        const {
            rows: [plugin],
        } = await hub.db.postgresQuery(
            `SELECT * FROM posthog_pluginsourcefile WHERE plugin_id = $1 AND filename = $2`,
            [60, 'frontend.tsx'],
            ''
        )
        expect(plugin.transpiled).toEqual(null)
        expect(plugin.status).toEqual('ERROR')
        expect(plugin.error).toContain(`SyntaxError: /frontend.tsx: Unexpected token (1:24)`)
        expect(plugin.error).toContain(`export const scene = {}/`)
    })

    test('getTranspilationLock returns just once', async () => {
        const localPluginData = {
            ...mockPluginSourceCode(),
            source__index_ts: `function processEvent (event, meta) { event.properties={"x": 1}; return event }`,
            source__frontend_tsx: `export const scene = {}`,
        }

        const organizationId = await createOrganization(hub.postgres)
        const teamId = await createTeam(hub.postgres, organizationId)
        const { id: _, ...pluginData } = localPluginData
        const plugin = await createPlugin(hub.postgres, {
            ...pluginData,
            organization_id: organizationId,
        })
        const { id: __, ...pluginConfigData } = pluginConfig39
        await createPluginConfig(hub.postgres, { ...pluginConfigData, plugin_id: plugin.id, team_id: teamId })

        const getStatus = async () =>
            (
                await hub.db.postgresQuery(
                    `SELECT status FROM posthog_pluginsourcefile WHERE plugin_id = $1 AND filename = $2`,
                    [60, 'frontend.tsx'],
                    ''
                )
            )?.rows?.[0]?.status || null

        expect(await getStatus()).toEqual('TRANSPILED')
        expect(await hub.db.getPluginTranspilationLock(60, 'frontend.tsx')).toEqual(false)
        expect(await hub.db.getPluginTranspilationLock(60, 'frontend.tsx')).toEqual(false)

        await hub.db.postgresQuery(
            'UPDATE posthog_pluginsourcefile SET transpiled = NULL, status = NULL WHERE filename = $1',
            ['frontend.tsx'],
            ''
        )

        expect(await hub.db.getPluginTranspilationLock(60, 'frontend.tsx')).toEqual(true)
        expect(await hub.db.getPluginTranspilationLock(60, 'frontend.tsx')).toEqual(false)
        expect(await getStatus()).toEqual('LOCKED')
    })

    test('reloading plugins after config changes', async () => {
        const makePlugin = (id: number, updated_at = '2020-11-02'): any => ({
            ...plugin60,
            id,
            plugin_type: 'source',
            source: setOrderCode(60),
            updated_at,
        })
        const makeConfig = (plugin_id: number, id: number, order: number, updated_at = '2020-11-02'): any => ({
            ...pluginConfig39,
            plugin_id,
            id,
            order,
            updated_at,
        })

        const setOrderCode = (id: number) => {
            return `
            function processEvent(event) {
                if (!event.properties.plugins) { event.properties.plugins = [] }
                event.properties.plugins.push(${id})
                return event
            }
        `
        }

        getPluginRows.mockReturnValue([makePlugin(60), makePlugin(61), makePlugin(62), makePlugin(63)])
        getPluginAttachmentRows.mockReturnValue([])
        getPluginConfigRows.mockReturnValue([
            makeConfig(60, 39, 0),
            makeConfig(61, 41, 1),
            makeConfig(62, 40, 3),
            makeConfig(63, 42, 2),
        ])

        await setupPlugins(hub)
        await loadSchedule(hub)

        expect(loadPlugin).toHaveBeenCalledTimes(4)
        expect(Array.from(hub.plugins.keys())).toEqual(expect.arrayContaining([60, 61, 62, 63]))
        expect(Array.from(hub.pluginConfigs.keys())).toEqual(expect.arrayContaining([39, 40, 41, 42]))

        expect(hub.pluginConfigsPerTeam.get(pluginConfig39.team_id)?.map((c) => [c.id, c.order])).toEqual([
            [39, 0],
            [41, 1],
            [42, 2],
            [40, 3],
        ])

        getPluginRows.mockReturnValue([makePlugin(60), makePlugin(61), makePlugin(63, '2021-02-02'), makePlugin(64)])
        getPluginAttachmentRows.mockReturnValue([])
        getPluginConfigRows.mockReturnValue([
            makeConfig(60, 39, 0),
            makeConfig(61, 41, 3, '2021-02-02'),
            makeConfig(63, 42, 2),
            makeConfig(64, 43, 1),
        ])

        await setupPlugins(hub)
        await loadSchedule(hub)

        expect(loadPlugin).toHaveBeenCalledTimes(4 + 3)
        expect(Array.from(hub.plugins.keys())).toEqual(expect.arrayContaining([60, 61, 63, 64]))
        expect(Array.from(hub.pluginConfigs.keys())).toEqual(expect.arrayContaining([39, 41, 42, 43]))

        expect(hub.pluginConfigsPerTeam.get(pluginConfig39.team_id)?.map((c) => [c.id, c.order])).toEqual([
            [39, 0],
            [43, 1],
            [42, 2],
            [41, 3],
        ])
    })

    test("capabilities don't reload without changes", async () => {
        getPluginRows.mockReturnValueOnce([{ ...plugin60 }]).mockReturnValueOnce([
            {
                ...plugin60,
                capabilities: { jobs: [], scheduled_tasks: [], methods: ['processEvent'] },
            },
        ]) // updated in DB via first `setPluginCapabilities` call.
        getPluginAttachmentRows.mockReturnValue([pluginAttachment1])
        getPluginConfigRows.mockReturnValue([pluginConfig39])

        await setupPlugins(hub)
        const pluginConfig = hub.pluginConfigs.get(39)!

        await pluginConfig.vm?.resolveInternalVm
        // async loading of capabilities
        expect(setPluginCapabilities.mock.calls.length).toBe(1)

        pluginConfig.updated_at = new Date().toISOString()
        // config is changed, but capabilities haven't changed

        await setupPlugins(hub)
        const newPluginConfig = hub.pluginConfigs.get(39)!

        await newPluginConfig.vm?.resolveInternalVm
        // async loading of capabilities

        expect(newPluginConfig.plugin).not.toBe(pluginConfig.plugin)
        expect(setPluginCapabilities.mock.calls.length).toBe(1)
        expect(newPluginConfig.plugin!.capabilities).toEqual(pluginConfig.plugin!.capabilities)
    })

    test.skip('exportEvents automatically sets metrics', async () => {
        getPluginRows.mockReturnValueOnce([
            mockPluginWithSourceFiles(`
            export function exportEvents() {}
        `),
        ])
        getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
        getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

        await setupPlugins(hub)
        const pluginConfig = hub.pluginConfigs.get(39)!

        expect(pluginConfig.plugin!.metrics).toEqual({
            events_delivered_successfully: 'sum',
            events_seen: 'sum',
            other_errors: 'sum',
            retry_errors: 'sum',
            undelivered_events: 'sum',
        })
    })

    describe('loadSchedule()', () => {
        const mockConfig = (tasks: any) => ({ vm: { getScheduledTasks: () => Promise.resolve(tasks) } })

        const hub = {
            pluginConfigs: new Map(
                Object.entries({
                    1: {},
                    2: mockConfig({ runEveryMinute: null, runEveryHour: () => 123 }),
                    3: mockConfig({ runEveryMinute: () => 123, foo: () => 'bar' }),
                })
            ),
        } as any

        it('sets server.pluginSchedule once all plugins are ready', async () => {
            const promise = loadSchedule(hub)
            expect(hub.pluginSchedule).toEqual(null)

            await promise

            expect(hub.pluginSchedule).toEqual({
                runEveryMinute: ['3'],
                runEveryHour: ['2'],
                runEveryDay: [],
            })
        })
    })
})
