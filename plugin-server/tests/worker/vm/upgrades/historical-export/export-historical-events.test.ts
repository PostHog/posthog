import { PluginMeta } from '@posthog/plugin-scaffold'
import deepmerge from 'deepmerge'

import { Hub, PluginConfig, PluginConfigVMInternalResponse } from '../../../../../src/types'
import { createHub } from '../../../../../src/utils/db/hub'
import { createStorage } from '../../../../../src/worker/vm/extensions/storage'
import { createUtils } from '../../../../../src/worker/vm/extensions/utilities'
import { addHistoricalEventsExportCapability } from '../../../../../src/worker/vm/upgrades/historical-export/export-historical-events'
import { ExportHistoricalEventsUpgrade } from '../../../../../src/worker/vm/upgrades/utils/utils'
import { pluginConfig39 } from '../../../../helpers/plugins'

jest.mock('../../../../../src/utils/status')

describe('addHistoricalEventsExportCapability()', () => {
    let hub: Hub
    let closeHub: () => Promise<void>
    let _pluginConfig39: PluginConfig

    beforeEach(async () => {
        ;[hub, closeHub] = await createHub()

        _pluginConfig39 = { ...pluginConfig39 }
    })

    afterEach(async () => {
        await closeHub()
    })

    function addCapabilities(overrides?: any) {
        const mockVM = deepmerge(overrides, {
            methods: {
                exportEvents: jest.fn(),
            },
            tasks: {
                schedule: {},
                job: {},
            },
            meta: {
                storage: createStorage(hub, _pluginConfig39),
                utils: createUtils(hub, _pluginConfig39.id),
                jobs: {
                    exportHistoricalEvents: jest.fn().mockReturnValue(jest.fn()),
                },
                global: {},
            },
        }) as unknown as PluginConfigVMInternalResponse<PluginMeta<ExportHistoricalEventsUpgrade>>

        addHistoricalEventsExportCapability(hub, _pluginConfig39, mockVM)

        return mockVM
    }

    it('adds new methods, scheduled tasks and jobs', () => {
        const vm = addCapabilities()

        expect(Object.keys(vm.methods)).toEqual(['exportEvents', 'setupPlugin'])
        expect(Object.keys(vm.tasks.schedule)).toEqual(['runEveryMinute'])
        expect(Object.keys(vm.tasks.job)).toEqual(['exportHistoricalEvents', 'Export historical events'])
        expect(Object.keys(vm.meta.global)).toEqual([
            'exportHistoricalEvents',
            'initTimestampsAndCursor',
            'setTimestampBoundaries',
            'updateProgressBar',
        ])
    })

    it('registers public job spec theres not currently a spec', () => {
        const addOrUpdatePublicJobSpy = jest.spyOn(hub.db, 'addOrUpdatePublicJob')
        addCapabilities()

        expect(addOrUpdatePublicJobSpy).toHaveBeenCalledWith(60, 'Export historical events', {
            payload: {
                dateFrom: { required: true, title: 'Export start date', type: 'date' },
                dateTo: { required: true, title: 'Export end date', type: 'date' },
            },
        })
    })

    it('updates plugin job spec if current spec is outdated', () => {
        const addOrUpdatePublicJobSpy = jest.spyOn(hub.db, 'addOrUpdatePublicJob')

        _pluginConfig39.plugin = {
            public_jobs: {
                'Export historical events': { payload: { foo: 'bar' } },
            },
        } as any

        addCapabilities()

        expect(addOrUpdatePublicJobSpy).toHaveBeenCalledWith(60, 'Export historical events', {
            payload: {
                dateFrom: { required: true, title: 'Export start date', type: 'date' },
                dateTo: { required: true, title: 'Export end date', type: 'date' },
            },
        })
    })

    it('does not update plugin job spec if current spec matches stored spec', () => {
        const addOrUpdatePublicJobSpy = jest.spyOn(hub.db, 'addOrUpdatePublicJob')

        _pluginConfig39.plugin = {
            public_jobs: {
                'Export historical events': {
                    payload: {
                        dateFrom: { required: true, title: 'Export start date', type: 'date' },
                        dateTo: { required: true, title: 'Export end date', type: 'date' },
                    },
                },
            },
        } as any

        addCapabilities()

        expect(addOrUpdatePublicJobSpy).not.toHaveBeenCalled()
    })

    describe('setupPlugin()', () => {
        it('calls original setupPlugin()', async () => {
            const setupPlugin = jest.fn()
            const vm = addCapabilities({ methods: { setupPlugin } })

            await vm.methods.setupPlugin!()

            expect(setupPlugin).toHaveBeenCalled()
        })
    })
})
