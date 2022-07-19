import { Hub, LogLevel, PluginCapabilities } from '../../src/types'
import { createHub } from '../../src/utils/db/hub'
import { getVMPluginCapabilities, shouldSetupPluginInServer } from '../../src/worker/vm/capabilities'
import { createPluginConfigVM } from '../../src/worker/vm/vm'
import { pluginConfig39 } from '../helpers/plugins'

describe('capabilities', () => {
    describe('getVMPluginCapabilities()', () => {
        let hub: Hub
        let closeHub: () => Promise<void>

        beforeAll(async () => {
            console.info = jest.fn() as any
            console.warn = jest.fn() as any
            ;[hub, closeHub] = await createHub({ LOG_LEVEL: LogLevel.Warn })
        })

        afterAll(async () => {
            await closeHub()
        })

        function getCapabilities(indexJs: string): PluginCapabilities {
            const vm = createPluginConfigVM(hub, pluginConfig39, indexJs)
            return getVMPluginCapabilities(vm)
        }

        it('handles processEvent', () => {
            const capabilities = getCapabilities(`
                function processEvent (event, meta) { return null }
            `)
            expect(capabilities).toEqual({ jobs: [], scheduled_tasks: [], methods: ['processEvent'] })
        })

        it('handles setupPlugin', () => {
            const capabilities = getCapabilities(`
                function setupPlugin (meta) { meta.global.key = 'value' }
                function processEvent (event, meta) { event.properties={"x": 1}; return event }
            `)
            expect(capabilities).toEqual({ jobs: [], scheduled_tasks: [], methods: ['setupPlugin', 'processEvent'] })
        })

        it('handles all capabilities', () => {
            const capabilities = getCapabilities(`
                export function processEvent (event, meta) { event.properties={"x": 1}; return event }
                export function randomFunction (event, meta) { return event}
                export function onEvent (event, meta) { return event }
                export function onSnapshot (event, meta) { return event }

                export function runEveryHour(meta) {console.log('1')}

                export const jobs = {
                    x: (event, meta) => console.log(event)
                }
            `)
            expect(capabilities).toEqual({
                jobs: ['x'],
                scheduled_tasks: ['runEveryHour'],
                methods: ['onEvent', 'onSnapshot', 'processEvent'],
            })
        })
    })

    describe('shouldSetupPluginInServer()', () => {
        describe('no capabilities', () => {
            it('returns false if the server has no capabilities', () => {
                const shouldSetupPlugin = shouldSetupPluginInServer(
                    {},
                    { methods: ['processEvent', 'onEvent'], scheduled_tasks: ['runEveryMinute'], jobs: ['someJob'] }
                )
                expect(shouldSetupPlugin).toEqual(false)
            })

            it('returns false if the plugin has no capabilities', () => {
                const shouldSetupPlugin = shouldSetupPluginInServer(
                    { ingestion: true, processAsyncHandlers: true, processJobs: true, pluginScheduledTasks: true },
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
                const shouldSetupPlugin = shouldSetupPluginInServer(
                    { ingestion: true },
                    {
                        methods: ['onEvent', 'onSnapshot', 'exportEvents'],
                        scheduled_tasks: ['runEveryMinute'],
                        jobs: ['someJob'],
                    }
                )
                expect(shouldSetupPlugin).toEqual(false)
            })
        })

        describe('scheduled tasks', () => {
            it('returns true if plugin has any scheduled tasks and the server has pluginScheduledTasks capability', () => {
                const shouldSetupPlugin = shouldSetupPluginInServer(
                    { pluginScheduledTasks: true },
                    { scheduled_tasks: ['runEveryMinute'] }
                )
                expect(shouldSetupPlugin).toEqual(true)
            })

            it('returns false if plugin has no scheduled tasks and the server has only pluginScheduledTasks capability', () => {
                const shouldSetupPlugin = shouldSetupPluginInServer(
                    { pluginScheduledTasks: true },
                    { scheduled_tasks: [] }
                )
                expect(shouldSetupPlugin).toEqual(false)
            })
        })

        describe('jobs', () => {
            it('returns true if plugin has any jobs and the server has processJobs capability', () => {
                const shouldSetupPlugin = shouldSetupPluginInServer({ processJobs: true }, { jobs: ['someJob'] })
                expect(shouldSetupPlugin).toEqual(true)
            })

            it('returns false if plugin has no jobs and the server has only processJobs capability', () => {
                const shouldSetupPlugin = shouldSetupPluginInServer({ processJobs: true }, { jobs: [] })
                expect(shouldSetupPlugin).toEqual(false)
            })
        })

        describe('processAsyncHandlers', () => {
            it.each(['onEvent', 'onSnapshot', 'exportEvents'])(
                'returns true if plugin has %s and the server has processAsyncHandlers capability',
                (method) => {
                    const shouldSetupPlugin = shouldSetupPluginInServer(
                        { processAsyncHandlers: true },
                        { methods: [method] }
                    )
                    expect(shouldSetupPlugin).toEqual(true)
                }
            )

            it('returns false if plugin has none of onEvent, onSnapshot, or exportEvents and the server has only processAsyncHandlers capability', () => {
                const shouldSetupPlugin = shouldSetupPluginInServer({ processAsyncHandlers: true }, { methods: [] })
                expect(shouldSetupPlugin).toEqual(false)
            })
        })
    })
})
