import { PluginMeta } from '@posthog/plugin-scaffold'

import { Hub, PluginConfigVMInternalResponse } from '../../../../../src/types'
import { createHub } from '../../../../../src/utils/db/hub'
import { createStorage } from '../../../../../src/worker/vm/extensions/storage'
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

    function addCapabilities() {
        const mockVM = {
            methods: {
                exportEvents: jest.fn(),
            },
            tasks: {
                schedule: {},
                job: {},
            },
            meta: {
                storage: createStorage(hub, pluginConfig39),
                jobs: {
                    exportHistoricalEvents: jest.fn().mockReturnValue(jest.fn()),
                },
                global: {},
            },
        } as unknown as PluginConfigVMInternalResponse<PluginMeta<ExportHistoricalEventsUpgrade>>

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
})
