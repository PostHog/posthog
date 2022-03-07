import { RetryError } from '@posthog/plugin-scaffold'
import { mocked } from 'ts-jest/utils'

import { PluginLogEntrySource, PluginLogEntryType, PluginTaskType } from '../../src/types'
import { clearError } from '../../src/utils/db/error'
import { status } from '../../src/utils/status'
import { LazyPluginVM } from '../../src/worker/vm/lazy'
import { createPluginConfigVM } from '../../src/worker/vm/vm'
import { resetTestDatabase } from '../../tests/helpers/sql'
import { plugin60 } from '../helpers/plugins'
import { disablePlugin } from '../helpers/sqlMock'
import { PostgresLogsWrapper } from './../../src/utils/db/postgres-logs-wrapper'
import { VM_INIT_MAX_RETRIES } from './../../src/worker/vm/lazy'
import { plugin70 } from './../helpers/plugins'

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
    const baseDb = {
        queuePluginLogEntry: jest.fn(),
        batchInsertPostgresLogs: jest.fn(),
    }
    const postgresLogsWrapper = new PostgresLogsWrapper(baseDb as any)

    const db = {
        ...baseDb,
        postgresLogsWrapper,
    }

    const mockServer: any = { db }

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
            mocked(createPluginConfigVM).mockReturnValue(mockVM as any)
        })

        it('returns correct values for get methods', async () => {
            const vm = createVM()
            void initializeVm(vm)

            expect(await vm.getProcessEvent()).toEqual('processEvent')
            expect(await vm.getTask('someTask', PluginTaskType.Schedule)).toEqual(null)
            expect(await vm.getTask('runEveryMinute', PluginTaskType.Schedule)).toEqual('runEveryMinute')
            expect(await vm.getTasks(PluginTaskType.Schedule)).toEqual(mockVM.tasks.schedule)
        })

        it('logs info and clears errors on success', async () => {
            const vm = createVM()
            void initializeVm(vm)
            await vm.resolveInternalVm

            expect(status.info).toHaveBeenCalledWith('🔌', 'Loaded some plugin')
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
            mocked(createPluginConfigVM).mockImplementation(() => {
                throw error
            })

            void initializeVm(vm)

            expect(await vm.getProcessEvent()).toEqual(null)
            expect(await vm.getTask('runEveryMinute', PluginTaskType.Schedule)).toEqual(null)
            expect(await vm.getTasks(PluginTaskType.Schedule)).toEqual({})
        })

        it('vm init retries with exponential backoff before disabling plugin', async () => {
            let i = 0
            // throw a RetryError setting up the vm
            mocked(createPluginConfigVM).mockImplementation(() => {
                throw new Error('VM creation failed before setupPlugin')
            })

            await vm.initialize!('some log info', 'failure plugin')
            await vm.resolveInternalVm
            for (let i = 0; i < VM_INIT_MAX_RETRIES + 1; ++i) {
                jest.runOnlyPendingTimers()
                await vm.resolveInternalVm

                // plugin methods are always null throughout retries
                expect(await vm.getProcessEvent()).toEqual(null)
            }

            expect((status.warn as any).mock.calls).toEqual([
                ['⚠️', 'I failed without retry, please retry me too!'],
                ['⚠️', 'Failed to load failure plugin. Retrying in 5 s.'],
                ['⚠️', 'I failed, please retry me!'],
                ['⚠️', 'Failed to load failure plugin. Retrying in 10 s.'],
                ['⚠️', 'I failed, please retry me!'],
                ['⚠️', 'Failed to load failure plugin. Retrying in 20 s.'],
                ['⚠️', 'I failed, please retry me!'],
                ['⚠️', 'Failed to load failure plugin. Retrying in 40 s.'],
                ['⚠️', 'I failed, please retry me!'],
                [
                    '⚠️',
                    'Failed to load failure plugin. Disabling it due to too many retries – tried to load it 5 times before giving up.',
                ],
            ])

            // plugin gets disabled
            expect(disablePlugin).toHaveBeenCalledTimes(1)
            expect(disablePlugin).toHaveBeenCalledWith(mockServer, 39)
        })

        it('_setupPlugin handles retries correctly', async () => {
            const mockedRun = jest.fn()
            const mockVm = {
                run: mockedRun,
            }
            mockedRun.mockImplementation(() => {
                throw new Error('oh no')
            })

            const lazyVm = createVM()

            await lazyVm._setupPlugin(mockVm as any)
            await lazyVm._setupPlugin(mockVm as any)
            await lazyVm._setupPlugin(mockVm as any)
            await lazyVm._setupPlugin(mockVm as any)

            expect((status.warn as any).mock.calls).toEqual([
                ['⚠️', 'I failed, please retry me!'],
                ['⚠️', 'Failed to load failure plugin. Retrying in 5 s.'],
            ])

            expect((status.info as any).mock.calls).toEqual([])

            mockedRun.mockImplementation(() => 1)

            await lazyVm._setupPlugin(mockVm as any)

            expect((status.info as any).mock.calls).toEqual([
                ['🔌', expect.stringContaining('setupPlugin completed successfully for plugin test-maxmind-plugin')],
            ])

            // plugin never gets disabled
            expect(disablePlugin).toHaveBeenCalledTimes(0)
        })
    })
})
