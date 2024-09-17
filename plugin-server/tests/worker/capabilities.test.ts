import { Hub, LogLevel, PluginCapabilities } from '../../src/types'
import { closeHub, createHub } from '../../src/utils/db/hub'
import { getVMPluginCapabilities, shouldSetupPluginInServer } from '../../src/worker/vm/capabilities'
import { createPluginConfigVM } from '../../src/worker/vm/vm'
import { pluginConfig39 } from '../helpers/plugins'

jest.mock('../../src/worker/plugins/loadPluginsFromDB', () => ({
    loadPluginsFromDB: () => Promise.resolve({ plugins: [], pluginConfigs: [], pluginConfigsPerTeam: [] }),
}))

describe('capabilities', () => {
    let hub: Hub

    beforeAll(async () => {
        console.info = jest.fn() as any
        console.warn = jest.fn() as any
        hub = await createHub({ LOG_LEVEL: LogLevel.Warn })
    })

    afterAll(async () => {
        await closeHub(hub)
    })

    describe('getVMPluginCapabilities()', () => {
        function getCapabilities(indexJs: string): PluginCapabilities {
            const vm = createPluginConfigVM(hub, pluginConfig39, indexJs)
            return getVMPluginCapabilities(vm.methods)
        }

        it('handles processEvent', () => {
            const capabilities = getCapabilities(`
                function processEvent (event, meta) { return null }
            `)
            expect(capabilities).toEqual({ methods: ['processEvent'] })
        })

        it('handles setupPlugin', () => {
            const capabilities = getCapabilities(`
                function setupPlugin (meta) { meta.global.key = 'value' }
                function processEvent (event, meta) { event.properties={"x": 1}; return event }
            `)
            expect(capabilities).toEqual({ methods: ['setupPlugin', 'processEvent'] })
        })

        it('handles all capabilities', () => {
            const capabilities = getCapabilities(`
                export function processEvent (event, meta) { event.properties={"x": 1}; return event }
                export function randomFunction (event, meta) { return event}
                export function onEvent (event, meta) { return event }
                export function getSettings (meta) { return { handlesLargeBatches: true } }
                export function runEveryHour(meta) {console.log('1')}

                export const jobs = {
                    x: (event, meta) => console.log(event)
                }
            `)
            expect(capabilities).toEqual({
                methods: ['onEvent', 'processEvent', 'getSettings'],
            })
        })
    })

    describe('shouldSetupPluginInServer()', () => {
        describe('no capabilities', () => {
            it('returns false if the server has no capabilities', () => {
                const shouldSetupPlugin = shouldSetupPluginInServer({}, { methods: ['processEvent', 'onEvent'] })
                expect(shouldSetupPlugin).toEqual(false)
            })

            it('returns false if the plugin has no capabilities', () => {
                const shouldSetupPlugin = shouldSetupPluginInServer(
                    {
                        ingestion: true,
                        processAsyncOnEventHandlers: true,
                    },
                    {}
                )
                expect(shouldSetupPlugin).toEqual(false)
            })
        })

        describe('ingestion', () => {
            it('returns true if plugin has processEvent method and server has ingestion capability', () => {
                const shouldSetupPlugin = shouldSetupPluginInServer({ ingestion: true }, { methods: ['processEvent'] })
                expect(shouldSetupPlugin).toEqual(true)
            })

            it('returns false if plugin does not have processEvent method and server only has ingestion capability', () => {
                const shouldSetupPlugin = shouldSetupPluginInServer({ ingestion: true }, { methods: ['onEvent'] })
                expect(shouldSetupPlugin).toEqual(false)
            })
        })

        describe('ingestionOverflow', () => {
            it('returns true if plugin has processEvent method and server has ingestionOverflow capability', () => {
                const shouldSetupPlugin = shouldSetupPluginInServer(
                    { ingestionOverflow: true },
                    { methods: ['processEvent'] }
                )
                expect(shouldSetupPlugin).toEqual(true)
            })

            it('returns false if plugin does not have processEvent method and server only has ingestionOverflow capability', () => {
                const shouldSetupPlugin = shouldSetupPluginInServer(
                    { ingestionOverflow: true },
                    { methods: ['onEvent'] }
                )
                expect(shouldSetupPlugin).toEqual(false)
            })
        })

        describe('ingestionHistorical', () => {
            it('returns true if plugin has processEvent method and server has ingestionHistorical capability', () => {
                const shouldSetupPlugin = shouldSetupPluginInServer(
                    { ingestionHistorical: true },
                    { methods: ['processEvent'] }
                )
                expect(shouldSetupPlugin).toEqual(true)
            })

            it('returns false if plugin does not have processEvent method and server only has ingestionHistorical capability', () => {
                const shouldSetupPlugin = shouldSetupPluginInServer(
                    { ingestionHistorical: true },
                    { methods: ['onEvent'] }
                )
                expect(shouldSetupPlugin).toEqual(false)
            })
        })

        describe('processAsyncOnEventHandlers', () => {
            it.each(['onEvent'])(
                'returns true if plugin has %s and the server has processAsyncOnEventHandlers capability',
                (method) => {
                    const shouldSetupPlugin = shouldSetupPluginInServer(
                        { processAsyncOnEventHandlers: true },
                        { methods: [method] }
                    )
                    expect(shouldSetupPlugin).toEqual(true)
                }
            )

            it('returns false if plugin has none of onEvent and the server has only processAsyncOnEventHandlers capability', () => {
                const shouldSetupPlugin = shouldSetupPluginInServer(
                    { processAsyncOnEventHandlers: true },
                    { methods: [] }
                )
                expect(shouldSetupPlugin).toEqual(false)
            })

            it.each(['onEvent'])(
                'onEvent returns true if plugin has %s and the server has processAsyncOnEventHandlers capability',
                (method) => {
                    const shouldSetupPlugin = shouldSetupPluginInServer(
                        { processAsyncOnEventHandlers: true },
                        { methods: [method] }
                    )
                    expect(shouldSetupPlugin).toEqual(true)
                }
            )

            it('returns false if plugin has none of onEvent and the server has only processAsyncOnEventHandlers capability', () => {
                const shouldSetupPlugin = shouldSetupPluginInServer(
                    { processAsyncOnEventHandlers: true },
                    { methods: [] }
                )
                expect(shouldSetupPlugin).toEqual(false)
            })
        })
    })
})
