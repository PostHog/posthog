import { PluginMeta } from '@posthog/plugin-scaffold'
import deepmerge from 'deepmerge'

import { Hub, PluginConfigVMInternalResponse } from '../../../../../src/types'
import { createHub } from '../../../../../src/utils/db/hub'
import { createStorage } from '../../../../../src/worker/vm/extensions/storage'
import { createUtils } from '../../../../../src/worker/vm/extensions/utilities'
import {
    addHistoricalEventsExportCapabilityV2,
    ExportHistoricalEventsUpgradeV2,
    TestFunctions,
} from '../../../../../src/worker/vm/upgrades/historical-export/export-historical-events-v2'
import { pluginConfig39 } from '../../../../helpers/plugins'

jest.mock('../../../../../src/utils/status')

describe('addHistoricalEventsExportCapabilityV2()', () => {
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
        }) as unknown as PluginConfigVMInternalResponse<PluginMeta<ExportHistoricalEventsUpgradeV2>>

        addHistoricalEventsExportCapabilityV2(hub, pluginConfig39, mockVM)

        return mockVM
    }

    function getTestMethod<T extends keyof TestFunctions>(name: T): TestFunctions[T] {
        // @ts-expect-error testing-related schenanigans
        return (...args: any[]) => {
            const vm = addCapabilities()
            // @ts-expect-error testing-related schenanigans
            return vm.meta.global._testFunctions[name](...args)
        }
    }

    describe('progressBar()', () => {
        const progressBar = getTestMethod('progressBar')

        it('calculates progress correctly', () => {
            expect(progressBar(0)).toEqual('□□□□□□□□□□□□□□□□□□□□')
            expect(progressBar(1)).toEqual('■■■■■■■■■■■■■■■■■■■■')
            expect(progressBar(0.5)).toEqual('■■■■■■■■■■□□□□□□□□□□')
            expect(progressBar(0.7)).toEqual('■■■■■■■■■■■■■■□□□□□□')
            expect(progressBar(0.12)).toEqual('■■□□□□□□□□□□□□□□□□□□')
            expect(progressBar(0.12, 10)).toEqual('■□□□□□□□□□')
        })
    })
})
