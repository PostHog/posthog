import { PluginLogEntrySource, PluginLogEntryType, PluginTaskType } from '../../src/types'
import { status } from '../../src/utils/status'
import { LazyPluginVM } from '../../src/worker/vm/lazy'
import { createPluginConfigVM } from '../../src/worker/vm/vm'
import { plugin60 } from '../helpers/plugins'
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
            jest.mocked(createPluginConfigVM).mockImplementation(() => {
                throw error
            })

            void initializeVm(vm)

            expect(await vm.getProcessEvent()).toEqual(null)
            expect(await vm.getTask('runEveryMinute', PluginTaskType.Schedule)).toEqual(null)
            expect(await vm.getTasks(PluginTaskType.Schedule)).toEqual({})
        })

        it('disables plugin if vm creation fails before setupPlugin', async () => {
            jest.mocked(createPluginConfigVM).mockImplementation(() => {
                throw new Error('VM creation failed before setupPlugin')
            })

            await vm.initialize!('some log info', 'failure plugin')
            await vm.resolveInternalVm

            expect((status.warn as any).mock.calls).toEqual([['⚠️', 'VM creation failed before setupPlugin']])

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

            expect(mockServer.db.queuePluginLogEntry).toHaveBeenLastCalledWith(
                expect.objectContaining({
                    instanceId: undefined,
                    message: expect.stringContaining('oh no'),
                })
            )
            await lazyVm._setupPlugin(mockVm as any)
            await lazyVm._setupPlugin(mockVm as any)
            await lazyVm._setupPlugin(mockVm as any)

            expect((status.warn as any).mock.calls).toEqual([
                ['⚠️', expect.stringContaining('setupPlugin failed for plugin test-maxmind-plugin')],
                ['⚠️', expect.stringContaining('setupPlugin failed for plugin test-maxmind-plugin')],
                ['⚠️', expect.stringContaining('setupPlugin failed for plugin test-maxmind-plugin')],
                ['⚠️', expect.stringContaining('setupPlugin failed for plugin test-maxmind-plugin')],
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
