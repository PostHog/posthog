import { PluginMeta } from '@posthog/plugin-scaffold'
import deepmerge from 'deepmerge'

import { Hub, PluginConfigVMInternalResponse } from '../../../../../src/types'
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

    beforeEach(async () => {
        ;[hub, closeHub] = await createHub()
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
                storage: createStorage(hub, pluginConfig39),
                utils: createUtils(hub, pluginConfig39.id),
                jobs: {
                    exportHistoricalEvents: jest.fn().mockReturnValue(jest.fn()),
                },
                global: {},
            },
        }) as unknown as PluginConfigVMInternalResponse<PluginMeta<ExportHistoricalEventsUpgrade>>

        addHistoricalEventsExportCapability(hub, pluginConfig39, mockVM)

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

    describe('setupPlugin()', () => {
        it('calls original setupPlugin()', async () => {
            const setupPlugin = jest.fn()
            const vm = addCapabilities({ methods: { setupPlugin } })

            await vm.methods.setupPlugin!()

            expect(setupPlugin).toHaveBeenCalled()
        })
    })
})
