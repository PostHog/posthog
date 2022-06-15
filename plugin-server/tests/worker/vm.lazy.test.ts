import { RetryError } from '@posthog/plugin-scaffold'

import { PluginLogEntrySource, PluginLogEntryType, PluginTaskType } from '../../src/types'
import { status } from '../../src/utils/status'
import { LazyPluginVM } from '../../src/worker/vm/lazy'
import { createPluginConfigVM } from '../../src/worker/vm/vm'
import { plugin60, pluginConfig39 } from '../helpers/plugins'
import { disablePlugin } from '../helpers/sqlMock'

jest.mock('../../src/utils/db/error')
jest.mock('../../src/utils/status')
jest.mock('../../src/utils/db/sql')
jest.mock('../../src/worker/vm/vm')

const mockConfig = {
    plugin_id: 60,
    team_id: 2,
    id: 39,
    plugin: { ...plugin60 },
}

describe('LazyPluginVM', () => {
    const db = {
        queuePluginLogEntry: jest.fn(),
        celeryApplyAsync: jest.fn(),
    }

    const mockServer: any = {
        db,
        capabilities: { ingestion: true, pluginScheduledTasks: true, processJobs: true, processAsyncHandlers: true },
    }

    const createVM = () => {
        const lazyVm = new LazyPluginVM(mockServer, mockConfig as any)
        lazyVm.ready = true
        return lazyVm
    }

    const initializeVm = (vm: LazyPluginVM) => vm.initialize!('', 'some plugin')

    const mockVM = {
        vm: 'vm',
        methods: {
            processEvent: 'processEvent',
        },
        tasks: {
            schedule: {
                runEveryMinute: 'runEveryMinute',
            },
        },
        vmResponseVariable: 'arghhhhh',
    }

    describe('VM creation succeeds', () => {
        beforeEach(() => {
            jest.mocked(createPluginConfigVM).mockReturnValue(mockVM as any)
        })

        it('returns correct values for get methods', async () => {
            const vm = createVM()
            void initializeVm(vm)

            expect(await vm.getProcessEvent()).toEqual('processEvent')
            expect(await vm.getTask('someTask', PluginTaskType.Schedule)).toEqual(null)
            expect(await vm.getTask('runEveryMinute', PluginTaskType.Schedule)).toEqual('runEveryMinute')
            expect(await vm.getScheduledTasks()).toEqual(mockVM.tasks.schedule)
        })

        it('logs info and clears errors on success', async () => {
            const vm = createVM()
            void initializeVm(vm)
            await vm.resolveInternalVm

            expect(status.info).toHaveBeenCalledWith('🔌', 'Loaded some plugin.')
            expect(mockServer.db.queuePluginLogEntry).toHaveBeenCalledWith(
                expect.objectContaining({
                    instanceId: undefined,
                    message: expect.stringContaining('Plugin loaded'),
                    pluginConfig: expect.anything(),
                    source: PluginLogEntrySource.System,
                    type: PluginLogEntryType.Info,
                })
            )
        })
    })

    describe('VM creation fails', () => {
        const error = new Error()
        let vm = createVM()
        jest.useFakeTimers()

        beforeEach(() => {
            vm = createVM()
        })

        afterEach(() => {
            vm.clearRetryTimeoutIfExists()
        })

        it('returns empty values for get methods', async () => {
            jest.mocked(createPluginConfigVM).mockImplementation(() => {
                throw error
            })

            void initializeVm(vm)

            expect(await vm.getProcessEvent()).toEqual(null)
            expect(await vm.getTask('runEveryMinute', PluginTaskType.Schedule)).toEqual(null)
            expect(await vm.getScheduledTasks()).toEqual({})
        })

        it('disables plugin if vm creation fails before setupPlugin', async () => {
            jest.mocked(createPluginConfigVM).mockImplementation(() => {
                throw new Error('VM creation failed before setupPlugin')
            })

            await vm.initialize!('some log info', 'failure plugin')
            await vm.resolveInternalVm

            expect((status.warn as any).mock.calls).toEqual([
                ['⚠️', 'Failed to load failure plugin. Error: VM creation failed before setupPlugin'],
            ])

            // plugin gets disabled
            expect(disablePlugin).toHaveBeenCalledTimes(1)
            expect(disablePlugin).toHaveBeenCalledWith(mockServer, 39)
        })

        it('_setupPlugin handles RetryError succeeding at last', async () => {
            const mockedRun = jest.fn()
            const mockVm = {
                run: mockedRun,
            }
            mockedRun.mockImplementation(() => {
                throw new RetryError()
            })

            const lazyVm = createVM()

            await lazyVm._setupPlugin(mockVm as any)

            expect(mockServer.db.queuePluginLogEntry).toHaveBeenLastCalledWith(
                expect.objectContaining({
                    instanceId: undefined,
                    message: expect.stringContaining('setupPlugin failed with RetryError (attempt 1/5)'),
                })
            )
            await lazyVm._setupPlugin(mockVm as any)
            await lazyVm._setupPlugin(mockVm as any)
            await lazyVm._setupPlugin(mockVm as any)

            expect((status.warn as any).mock.calls).toEqual([
                [
                    '⚠️',
                    expect.stringContaining(
                        'setupPlugin failed with RetryError (attempt 1/5) for plugin test-maxmind-plugin'
                    ),
                ],
                [
                    '⚠️',
                    expect.stringContaining(
                        'setupPlugin failed with RetryError (attempt 2/5) for plugin test-maxmind-plugin'
                    ),
                ],
                [
                    '⚠️',
                    expect.stringContaining(
                        'setupPlugin failed with RetryError (attempt 3/5) for plugin test-maxmind-plugin'
                    ),
                ],
                [
                    '⚠️',
                    expect.stringContaining(
                        'setupPlugin failed with RetryError (attempt 4/5) for plugin test-maxmind-plugin'
                    ),
                ],
            ])

            expect((status.info as any).mock.calls).toEqual([])

            // The 5th, final attempt succeeds because we re-mock the implementation to succeed. Yay!
            mockedRun.mockImplementation(() => 1)

            await expect(lazyVm._setupPlugin(mockVm as any)).resolves.toBeUndefined()

            expect((status.info as any).mock.calls).toEqual([
                ['🔌', expect.stringContaining('setupPlugin succeeded for plugin test-maxmind-plugin')],
            ])

            // Plugin does not get disabled
            expect(disablePlugin).toHaveBeenCalledTimes(0)
        })

        it('_setupPlugin handles RetryError never succeeding', async () => {
            const mockedRun = jest.fn()
            const mockVm = {
                run: mockedRun,
            }
            mockedRun.mockImplementation(() => {
                throw new RetryError()
            })

            const lazyVm = createVM()

            await lazyVm._setupPlugin(mockVm as any)

            expect(mockServer.db.queuePluginLogEntry).toHaveBeenLastCalledWith(
                expect.objectContaining({
                    instanceId: undefined,
                    message: expect.stringContaining('setupPlugin failed with RetryError (attempt 1/5)'),
                })
            )
            await lazyVm._setupPlugin(mockVm as any)
            await lazyVm._setupPlugin(mockVm as any)
            await lazyVm._setupPlugin(mockVm as any)

            expect(jest.mocked(status.warn).mock.calls).toEqual([
                [
                    '⚠️',
                    expect.stringContaining(
                        'setupPlugin failed with RetryError (attempt 1/5) for plugin test-maxmind-plugin'
                    ),
                ],
                [
                    '⚠️',
                    expect.stringContaining(
                        'setupPlugin failed with RetryError (attempt 2/5) for plugin test-maxmind-plugin'
                    ),
                ],
                [
                    '⚠️',
                    expect.stringContaining(
                        'setupPlugin failed with RetryError (attempt 3/5) for plugin test-maxmind-plugin'
                    ),
                ],
                [
                    '⚠️',
                    expect.stringContaining(
                        'setupPlugin failed with RetryError (attempt 4/5) for plugin test-maxmind-plugin'
                    ),
                ],
            ])

            // Setup never succeeds
            await expect(lazyVm._setupPlugin(mockVm as any)).rejects.toThrow(
                'setupPlugin failed with RetryError (attempt 5/5) for plugin test-maxmind-plugin'
            )

            // Plugin gets disabled due to failure
            expect(disablePlugin).toHaveBeenCalledTimes(1)
            // An email to project members about the failure is queued
            expect(mockServer.db.celeryApplyAsync).toHaveBeenCalledWith('posthog.tasks.email.send_fatal_plugin_error', [
                pluginConfig39.id,
                null,
                'RetryError (attempt 5/5)',
                false,
            ])
        })
    })
})
