import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import * as api from '../../generated/api'
import type { WarehouseStatusResponseApi } from '../../generated/api.schemas'
import { warehouseConsoleLogic } from './warehouseConsoleLogic'
import {
    WarehousePageKind,
    warehouseConsoleRedirectLogic,
    warehouseConsoleRedirectTarget,
} from './warehouseConsoleRedirectLogic'

function status(state: string, trinoState: string): WarehouseStatusResponseApi {
    return {
        state,
        trino: { state: trinoState, hoglake: false, connection: null },
    } as unknown as WarehouseStatusResponseApi
}

// The router adds the project prefix that `urls` leaves to the caller.
const currentPath = (): string => router.values.location.pathname.replace(/^\/project\/\d+/, '')

describe('warehouseConsoleRedirectLogic', () => {
    describe('warehouseConsoleRedirectTarget', () => {
        it.each([
            ['console', 'loading', null],
            ['console', 'error', null],
            ['console', 'no_warehouse', 'upsell'],
            ['console', 'not_ready', null],
            ['console', 'ready', null],
            ['upsell', 'loading', null],
            ['upsell', 'error', null],
            ['upsell', 'no_warehouse', null],
            ['upsell', 'not_ready', 'overview'],
            ['upsell', 'ready', 'overview'],
            ['setup', 'loading', null],
            ['setup', 'error', null],
            ['setup', 'no_warehouse', null],
            ['setup', 'not_ready', null],
            ['setup', 'ready', null],
        ] as const)('sends a %s page in state %s to %s', (kind, consoleState, target) => {
            const targets = { upsell: urls.warehouse(), overview: urls.warehouseOverview() }
            expect(warehouseConsoleRedirectTarget(kind, consoleState)).toBe(target ? targets[target] : null)
        })
    })

    describe('logic', () => {
        beforeEach(() => {
            initKeaTests()
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.MANAGED_WAREHOUSE_CONSOLE]: true })
        })

        afterEach(() => jest.restoreAllMocks())

        const noWarehouse = (): Promise<unknown> => Promise.reject({ status: 404 })
        const failedLoad = (): Promise<unknown> => Promise.reject(new Error('boom'))
        const readyWarehouse = (): Promise<unknown> => Promise.resolve(status('ready', 'ready'))
        const provisioning = (): Promise<unknown> => Promise.resolve(status('provisioning', 'pending'))

        it.each([
            ['console', 'no warehouse', urls.warehouse(), 'loadWarehouseStatusSuccess', noWarehouse],
            ['console', 'a failed load', null, 'loadWarehouseStatusFailure', failedLoad],
            ['console', 'a ready warehouse', null, 'loadWarehouseStatusSuccess', readyWarehouse],
            ['upsell', 'no warehouse', null, 'loadWarehouseStatusSuccess', noWarehouse],
            ['upsell', 'a failed load', null, 'loadWarehouseStatusFailure', failedLoad],
            ['upsell', 'a ready warehouse', urls.warehouseOverview(), 'loadWarehouseStatusSuccess', readyWarehouse],
            [
                'upsell',
                'a provisioning warehouse',
                urls.warehouseOverview(),
                'loadWarehouseStatusSuccess',
                provisioning,
            ],
            ['setup', 'no warehouse', null, 'loadWarehouseStatusSuccess', noWarehouse],
        ] as [WarehousePageKind, string, string | null, string, () => Promise<unknown>][])(
            'on a %s page with %s, goes to %s',
            async (kind, _name, target, settledAction, response) => {
                jest.spyOn(api, 'dataWarehouseWarehouseStatusRetrieve').mockImplementation(response as never)
                router.actions.push(urls.warehouseQueries())
                const logic = warehouseConsoleRedirectLogic({ kind })
                logic.mount()

                await expectLogic(warehouseConsoleLogic).toDispatchActions([settledAction])
                expect(currentPath()).toBe(target ?? urls.warehouseQueries())
            }
        )

        it('stays put while the status is loading', () => {
            jest.spyOn(api, 'dataWarehouseWarehouseStatusRetrieve').mockReturnValue(new Promise(() => {}) as never)
            router.actions.push(urls.warehouseQueries())
            warehouseConsoleRedirectLogic({ kind: 'console' }).mount()

            expect(currentPath()).toBe(urls.warehouseQueries())
        })
    })
})
