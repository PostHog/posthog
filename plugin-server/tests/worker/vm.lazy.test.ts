import { RetryError } from '@posthog/plugin-scaffold'

import { PluginLogEntrySource, PluginLogEntryType } from '../../src/types'
import { logger } from '../../src/utils/logger'
import { LazyPluginVM } from '../../src/worker/vm/lazy'
import { createPluginConfigVM } from '../../src/worker/vm/vm'
import { plugin60, pluginConfig39 } from '../helpers/plugins'

jest.mock('../../src/utils/db/error')
jest.mock('../../src/utils/logger')
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
    }

    const mockServer: any = {
        db,
        capabilities: {
            ingestionV2: true,
            processAsyncHandlers: true,
        },
        celery: {
            applyAsync: jest.fn(),
        },
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
        vmResponseVariable: 'arghhhhh',
    }

    describe('VM creation succeeds', () => {
        beforeEach(() => {
            jest.mocked(createPluginConfigVM).mockReturnValue(mockVM as any)
        })

        it('returns correct values for get methods', async () => {
            const vm = createVM()
            void initializeVm(vm)

            expect(await vm.getPluginMethod('processEvent')).toEqual('processEvent')
        })

        it('logs info and clears errors on success', async () => {
            const vm = createVM()
            void initializeVm(vm)
            await vm.resolveInternalVm

            expect(logger.debug).toHaveBeenCalledWith('🔌', 'Loaded some plugin.')
            expect(mockServer.db.queuePluginLogEntry).toHaveBeenCalledWith(
                expect.objectContaining({
                    instanceId: undefined,
                    message: expect.stringContaining('Plugin loaded'),
                    pluginConfig: expect.anything(),
                    source: PluginLogEntrySource.System,
                    type: PluginLogEntryType.Debug,
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

            expect(await vm.getPluginMethod('processEvent')).toEqual(null)
        })

        it('disables plugin if vm creation fails before setupPlugin', async () => {
            jest.mocked(createPluginConfigVM).mockImplementation(() => {
                throw new Error('VM creation failed before setupPlugin')
            })

            await vm.initialize!('some log info', 'failure plugin')
            await vm.resolveInternalVm

            expect((logger.warn as any).mock.calls).toEqual([
                ['⚠️', 'Failed to load failure plugin. Error: VM creation failed before setupPlugin'],
            ])
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

            expect((logger.warn as any).mock.calls).toEqual([
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

            expect((logger.info as any).mock.calls).toEqual([])

            // The 5th, final attempt succeeds because we re-mock the implementation to succeed. Yay!
            mockedRun.mockImplementation(() => 1)

            await expect(lazyVm._setupPlugin(mockVm as any)).resolves.toBeUndefined()

            expect((logger.info as any).mock.calls).toEqual([
                ['🔌', expect.stringContaining('setupPlugin succeeded for plugin test-maxmind-plugin')],
            ])
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

            expect(jest.mocked(logger.warn).mock.calls).toEqual([
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

            // An email to project members about the failure is queued
            expect(mockServer.celery.applyAsync).toHaveBeenCalledWith(
                'posthog.tasks.plugin_server.fatal_plugin_error',
                [pluginConfig39.id, null, 'RetryError (attempt 5/5)', false]
            )
        })
    })
})
