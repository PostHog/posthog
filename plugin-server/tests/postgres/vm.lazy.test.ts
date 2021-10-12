import { RetryError } from '@posthog/plugin-scaffold'
import { mocked } from 'ts-jest/utils'

import { PluginLogEntrySource, PluginLogEntryType, PluginTaskType } from '../../src/types'
import { clearError } from '../../src/utils/db/error'
import { status } from '../../src/utils/status'
import { LazyPluginVM } from '../../src/worker/vm/lazy'
import { createPluginConfigVM } from '../../src/worker/vm/vm'
import { plugin60 } from '../helpers/plugins'
import { disablePlugin } from '../helpers/sqlMock'
import { PostgresLogsWrapper } from './../../src/utils/db/postgres-logs-wrapper'
import { plugin70 } from './../helpers/plugins'

jest.mock('../../src/worker/vm/vm')
jest.mock('../../src/utils/db/error')
jest.mock('../../src/utils/status')
jest.mock('../../src/utils/db/sql')

const mockConfig = {
    plugin_id: 60,
    team_id: 2,
    id: 39,
    plugin: { ...plugin60 },
}

describe('LazyPluginVM', () => {
    const createVM = () => new LazyPluginVM()
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
    const initializeVm = (vm: LazyPluginVM) => vm.initialize!(mockServer, mockConfig as any, '', 'some plugin')

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
    }

    describe('VM creation succeeds', () => {
        beforeEach(() => {
            mocked(createPluginConfigVM).mockResolvedValue(mockVM as any)
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
            expect(clearError).toHaveBeenCalledWith(mockServer, mockConfig)
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
        const retryError = new RetryError('I failed, please retry me!')
        let vm = createVM()
        jest.useFakeTimers()

        const mockFailureConfig = {
            plugin_id: 70,
            team_id: 2,
            id: 35,
            plugin: { ...plugin70 },
        }

        beforeEach(() => {
            vm = createVM()
        })

        afterEach(() => {
            vm.clearRetryTimeoutIfExists()
        })

        it('returns empty values for get methods', async () => {
            mocked(createPluginConfigVM).mockRejectedValue(error)

            void initializeVm(vm)

            expect(await vm.getProcessEvent()).toEqual(null)
            expect(await vm.getTask('runEveryMinute', PluginTaskType.Schedule)).toEqual(null)
            expect(await vm.getTasks(PluginTaskType.Schedule)).toEqual({})
        })

        it('vm init retries 10x with exponential backoff before disabling plugin', async () => {
            // throw a RetryError setting up the vm
            mocked(createPluginConfigVM)
                .mockRejectedValueOnce(new Error('I failed without retry, please retry me too!'))
                .mockRejectedValue(retryError)

            await vm.initialize!(mockServer, mockFailureConfig as any, 'some log info', 'failure plugin')

            // try to initialize the vm 11 times (1 try + 10 retries)
            await vm.resolveInternalVm
            for (let i = 0; i < 10; ++i) {
                jest.runOnlyPendingTimers()
                await vm.resolveInternalVm

                // plugin methods are always null throughout retries
                expect(await vm.getProcessEvent()).toEqual(null)
            }

            // plugin setup is retried 15 times with exponential backoff
            expect((status.warn as any).mock.calls).toEqual([
                ['⚠️', 'I failed without retry, please retry me too!'],
                ['⚠️', 'Failed to load failure plugin. Retrying in 3 s.'],
                ['⚠️', 'I failed, please retry me!'],
                ['⚠️', 'Failed to load failure plugin. Retrying in 6 s.'],
                ['⚠️', 'I failed, please retry me!'],
                ['⚠️', 'Failed to load failure plugin. Retrying in 12 s.'],
                ['⚠️', 'I failed, please retry me!'],
                ['⚠️', 'Failed to load failure plugin. Retrying in 24 s.'],
                ['⚠️', 'I failed, please retry me!'],
                ['⚠️', 'Failed to load failure plugin. Retrying in 48 s.'],
                ['⚠️', 'I failed, please retry me!'],
                ['⚠️', 'Failed to load failure plugin. Retrying in 96 s.'],
                ['⚠️', 'I failed, please retry me!'],
                ['⚠️', 'Failed to load failure plugin. Retrying in 192 s.'],
                ['⚠️', 'I failed, please retry me!'],
                ['⚠️', 'Failed to load failure plugin. Retrying in 384 s.'],
                ['⚠️', 'I failed, please retry me!'],
                ['⚠️', 'Failed to load failure plugin. Retrying in 768 s.'],
                ['⚠️', 'I failed, please retry me!'],
                [
                    '⚠️',
                    'Failed to load failure plugin. Disabling it due to too many retries – tried to load it 10 times before giving up.',
                ],
            ])

            // plugin gets disabled
            expect(disablePlugin).toHaveBeenCalledTimes(1)
            expect(disablePlugin).toHaveBeenCalledWith(mockServer, 35)
        })

        it('vm init will retry on error and load plugin successfully on a retry', async () => {
            // throw a RetryError setting up the vm
            mocked(createPluginConfigVM).mockRejectedValueOnce(retryError)

            await vm.initialize!(mockServer, mockFailureConfig as any, 'some log info', 'failure plugin')
            await vm.resolveInternalVm

            // retry mechanism is called based on the error
            expect((status.warn as any).mock.calls).toEqual([
                ['⚠️', 'I failed, please retry me!'],
                ['⚠️', 'Failed to load failure plugin. Retrying in 3 s.'],
            ])

            // do not fail on the second try
            mocked(createPluginConfigVM).mockResolvedValue(mockVM as any)
            jest.runOnlyPendingTimers()
            await vm.resolveInternalVm

            // load plugin successfully
            expect((status.info as any).mock.calls).toEqual([['🔌', 'Loaded failure plugin']])

            // plugin doesn't get disabled
            expect(disablePlugin).toHaveBeenCalledTimes(0)
        })
    })
})
