import { Hub } from '../../src/types'
import { processError } from '../../src/utils/db/error'
import { closeHub, createHub } from '../../src/utils/db/hub'
import { loadPlugin } from '../../src/worker/plugins/loadPlugin'
import { setupPlugins } from '../../src/worker/plugins/setup'
import { LazyPluginVM } from '../../src/worker/vm/lazy'
import {
    commonOrganizationId,
    mockPluginSourceCode,
    mockPluginTempFolder,
    mockPluginWithSourceFiles,
    plugin60,
    pluginAttachment1,
    pluginConfig39,
} from '../helpers/plugins'
import { resetTestDatabase } from '../helpers/sql'
import { getPluginAttachmentRows, getPluginConfigRows, getPluginRows, setPluginCapabilities } from '../helpers/sqlMock'

jest.mock('../../src/utils/db/sql')
jest.mock('../../src/utils/logger')
jest.mock('../../src/utils/db/error')
jest.mock('../../src/worker/plugins/loadPlugin', () => {
    const { loadPlugin } = jest.requireActual('../../src/worker/plugins/loadPlugin')
    return { loadPlugin: jest.fn().mockImplementation(loadPlugin) }
})
jest.setTimeout(20_000)

describe('plugins', () => {
    let hub: Hub

    beforeEach(async () => {
        hub = await createHub({ LOG_LEVEL: 'info' })
        console.warn = jest.fn() as any
        await resetTestDatabase()
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    test('stateless plugins', async () => {
        const plugin = { ...plugin60, is_stateless: true }
        getPluginRows.mockReturnValueOnce([plugin])
        getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])
        getPluginConfigRows.mockReturnValueOnce([pluginConfig39, { ...pluginConfig39, id: 40, team_id: 1 }])

        await setupPlugins(hub)
        const { pluginConfigs } = hub

        expect(getPluginRows).toHaveBeenCalled()
        expect(getPluginAttachmentRows).toHaveBeenCalled()
        expect(getPluginConfigRows).toHaveBeenCalled()

        expect(Array.from(pluginConfigs.keys())).toEqual([39, 40])

        const pluginConfigTeam1 = pluginConfigs.get(40)!
        const pluginConfigTeam2 = pluginConfigs.get(39)!

        expect(pluginConfigTeam1.plugin).toEqual(plugin)
        expect(pluginConfigTeam2.plugin).toEqual(plugin)

        expect(pluginConfigTeam1.instance).toBeTruthy()
        expect(pluginConfigTeam2.instance).toBeTruthy()

        expect(pluginConfigTeam1.instance).toEqual(pluginConfigTeam2.instance)
    })

    test('local plugin with broken plugin.json does not do much', async () => {
        // silence some spam
        console.log = jest.fn()
        console.error = jest.fn()

        const [plugin, unlink] = mockPluginTempFolder(
            `function processEvent (event, meta) { event.properties.processed = true; return event }`,
            '{ broken: "plugin.json" -=- '
        )
        getPluginRows.mockReturnValueOnce([plugin])
        getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
        getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

        await setupPlugins(hub)
        const { pluginConfigs } = hub

        expect(processError).toHaveBeenCalledWith(
            hub,
            pluginConfigs.get(39)!,
            expect.stringContaining('Could not load "plugin.json" for plugin ')
        )

        unlink()
    })

    test('plugin with http urls must have source files', async () => {
        // silence some spam
        console.log = jest.fn()
        console.error = jest.fn()

        getPluginRows.mockReturnValueOnce([{ ...plugin60, source__index_ts: undefined }])
        getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
        getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

        await setupPlugins(hub)
        const { pluginConfigs } = hub

        expect(pluginConfigs.get(39)!.plugin!.url).toContain('https://')
        expect(processError).toHaveBeenCalledWith(
            hub,
            pluginConfigs.get(39)!,
            `Could not load source code for plugin test-maxmind-plugin ID 60 (organization ID ${commonOrganizationId}). Tried: index.js`
        )
    })

    test('plugin with source files loads capabilities', async () => {
        getPluginRows.mockReturnValueOnce([
            mockPluginWithSourceFiles(`
            function setupPlugin (meta) { meta.global.key = 'value' }
            function processEvent (event, meta) { event.properties={"x": 1}; return event }
        `),
        ])
        getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
        getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

        await setupPlugins(hub)
        const { pluginConfigs } = hub

        const pluginConfig = pluginConfigs.get(39)!

        await (pluginConfig.instance as LazyPluginVM)?.resolveInternalVm
        // async loading of capabilities

        expect(pluginConfig.plugin!.capabilities!.methods!.sort()).toEqual(['processEvent', 'setupPlugin'])
    })

    test('plugin with source files loads all capabilities, no random caps', async () => {
        getPluginRows.mockReturnValueOnce([
            mockPluginWithSourceFiles(`
            export function processEvent (event, meta) { event.properties={"x": 1}; return event }
            export function randomFunction (event, meta) { return event}
            export function onEvent (event, meta) { return event }
        `),
        ])
        getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
        getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

        await setupPlugins(hub)
        const { pluginConfigs } = hub

        const pluginConfig = pluginConfigs.get(39)!

        await (pluginConfig.instance as LazyPluginVM)?.resolveInternalVm
        // async loading of capabilities

        expect(pluginConfig.plugin!.capabilities!.methods!.sort()).toEqual(['onEvent', 'processEvent'])
    })

    test('plugin with source file loads capabilities', async () => {
        const [plugin, unlink] = mockPluginTempFolder(`
        function processEvent (event, meta) { event.properties={"x": 1}; return event }
        function randomFunction (event, meta) { return event}
        function onEvent (event, meta) { return event }
    `)

        getPluginRows.mockReturnValueOnce([plugin])
        getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
        getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

        await setupPlugins(hub)
        const { pluginConfigs } = hub

        const pluginConfig = pluginConfigs.get(39)!

        await (pluginConfig.instance as LazyPluginVM)?.resolveInternalVm
        // async loading of capabilities

        expect(pluginConfig.plugin!.capabilities!.methods!.sort()).toEqual(['onEvent', 'processEvent'])

        unlink()
    })

    test('plugin with source code loads capabilities', async () => {
        getPluginRows.mockReturnValueOnce([
            {
                ...mockPluginSourceCode(),
                source__index_ts: `
        function processEvent (event, meta) { event.properties={"x": 1}; return event }
        function randomFunction (event, meta) { return event}
        function onEvent (event, meta) { return event }`,
            },
        ])
        getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
        getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

        await setupPlugins(hub)
        const { pluginConfigs } = hub

        const pluginConfig = pluginConfigs.get(39)!

        await (pluginConfig.instance as LazyPluginVM)?.resolveInternalVm
        // async loading of capabilities

        expect(pluginConfig.plugin!.capabilities!.methods!.sort()).toEqual(['onEvent', 'processEvent'])
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
                capabilities: { methods: ['processEvent'] },
            },
        ]) // updated in DB via first `setPluginCapabilities` call.
        getPluginAttachmentRows.mockReturnValue([pluginAttachment1])
        getPluginConfigRows.mockReturnValue([pluginConfig39])

        await setupPlugins(hub)
        const pluginConfig = hub.pluginConfigs.get(39)!

        await (pluginConfig.instance as LazyPluginVM)?.resolveInternalVm
        // async loading of capabilities
        expect(setPluginCapabilities.mock.calls.length).toBe(1)

        pluginConfig.updated_at = new Date().toISOString()
        // config is changed, but capabilities haven't changed

        await setupPlugins(hub)
        const newPluginConfig = hub.pluginConfigs.get(39)!

        await (newPluginConfig.instance as LazyPluginVM)?.resolveInternalVm
        // async loading of capabilities

        expect(newPluginConfig.plugin).not.toBe(pluginConfig.plugin)
        expect(setPluginCapabilities.mock.calls.length).toBe(1)
        expect(newPluginConfig.plugin!.capabilities).toEqual(pluginConfig.plugin!.capabilities)
    })
})
