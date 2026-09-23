import { expectLogic } from 'kea-test-utils'

import { customProductsLogic } from '~/layout/panel-layout/ProjectTree/customProductsLogic'
import { useMocks } from '~/mocks/jest'
import { UserProductListItem } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { osInstalledAppsLogic } from './osInstalledAppsLogic'

const serverRow = (productPath: string): UserProductListItem => ({
    id: `id-${productPath}`,
    product_path: productPath,
    enabled: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
})

function deferred(): { promise: Promise<void>; resolve: () => void } {
    let resolve = (): void => {}
    const promise = new Promise<void>((r) => {
        resolve = r
    })
    return { promise, resolve }
}

describe('osInstalledAppsLogic', () => {
    let logic: ReturnType<typeof osInstalledAppsLogic.build>
    let serverPaths: string[]
    let writes: { product_path: string; enabled: boolean }[]
    let listCalls: number
    let failWrites: boolean
    let writeGate: Promise<void> | null
    let listGate: Promise<void> | null
    let failLists: boolean

    beforeEach(() => {
        listGate = null
        failLists = false
        serverPaths = ['Product analytics']
        writes = []
        listCalls = 0
        failWrites = false
        writeGate = null
        useMocks({
            get: {
                '/api/environments/:team_id/user_product_list/': async () => {
                    listCalls += 1
                    // The server answers with the list as it was when the request arrived.
                    const snapshot = serverPaths.map(serverRow)
                    await listGate
                    return failLists ? [500, { detail: 'nope' }] : [200, { results: snapshot }]
                },
            },
            patch: {
                '/api/environments/:team_id/user_product_list/bulk_update/': async ({ request }) => {
                    const { items } = (await request.json()) as {
                        items: { product_path: string; enabled: boolean }[]
                    }
                    await writeGate
                    if (failWrites) {
                        return [500, { detail: 'nope' }]
                    }
                    writes.push(...items)
                    for (const { product_path, enabled } of items) {
                        serverPaths = enabled
                            ? [...serverPaths.filter((path) => path !== product_path), product_path]
                            : serverPaths.filter((path) => path !== product_path)
                    }
                    return [200, { results: [] }]
                },
            },
        })
        initKeaTests()
        customProductsLogic.mount()
        customProductsLogic.actions.loadCustomProductsSuccess(serverPaths.map(serverRow))
        logic = osInstalledAppsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('installs and removes apps through the user product list, and the desktop list follows', async () => {
        await expectLogic(logic, () => {
            logic.actions.installApp('Surveys')
        }).toFinishAllListeners()

        expect(writes).toEqual([{ product_path: 'Surveys', enabled: true }])
        expect(customProductsLogic.values.enabledToolPaths).toEqual(new Set(['Product analytics', 'Surveys']))
        expect(logic.values.installedKeys).toEqual(new Set(['Product analytics', 'Surveys']))

        await expectLogic(logic, () => {
            logic.actions.removeApp('Product analytics')
        }).toFinishAllListeners()

        expect(writes[1]).toEqual({ product_path: 'Product analytics', enabled: false })
        expect(customProductsLogic.values.enabledToolPaths).toEqual(new Set(['Surveys']))
    })

    it('shows the app as installing while the write is in flight', async () => {
        const gate = deferred()
        writeGate = gate.promise

        logic.actions.installApp('Surveys')

        expect(logic.values.pendingKeys).toEqual(new Set(['Surveys']))
        expect(logic.values.installedKeys.has('Surveys')).toBe(true)

        gate.resolve()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.pendingKeys).toEqual(new Set())
    })

    it('goes back to the saved list when a write fails', async () => {
        failWrites = true

        await expectLogic(logic, () => {
            logic.actions.installApp('Surveys')
        }).toFinishAllListeners()

        expect(logic.values.installedKeys).toEqual(new Set(['Product analytics']))
        expect(customProductsLogic.values.enabledToolPaths).toEqual(new Set(['Product analytics']))
    })

    it('keeps an install when a load that started before the write answers after it', async () => {
        const gate = deferred()
        listGate = gate.promise
        customProductsLogic.actions.loadCustomProducts()

        await expectLogic(logic, () => {
            logic.actions.installApp('Surveys')
        }).toDispatchActions(['appWriteSettled'])
        listGate = null
        gate.resolve()
        await expectLogic(customProductsLogic).toFinishAllListeners()
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(customProductsLogic).toFinishAllListeners()

        expect(customProductsLogic.values.enabledToolPaths).toEqual(new Set(['Product analytics', 'Surveys']))
        expect(logic.values.installedKeys.has('Surveys')).toBe(true)
    })

    it('undoes a failed install even when the reload fails too', async () => {
        failWrites = true
        failLists = true

        await expectLogic(logic, () => {
            logic.actions.installApp('Surveys')
        }).toFinishAllListeners()
        await expectLogic(customProductsLogic).toFinishAllListeners()

        expect(logic.values.installedKeys).toEqual(new Set(['Product analytics']))
    })

    it('keeps an install when a reload answers with the list from before the write', async () => {
        const gate = deferred()
        writeGate = gate.promise

        logic.actions.installApp('Surveys')
        // The desktop reloads the list when the page regains focus, and that answer predates the write.
        customProductsLogic.actions.loadCustomProducts()
        await expectLogic(customProductsLogic).toDispatchActions(['loadCustomProductsSuccess'])

        expect(logic.values.installedKeys.has('Surveys')).toBe(true)

        gate.resolve()
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(customProductsLogic).toFinishAllListeners()

        expect(customProductsLogic.values.enabledToolPaths).toEqual(new Set(['Product analytics', 'Surveys']))
        expect(listCalls).toBe(2)
    })

    it('never installs or removes a system app', async () => {
        await expectLogic(logic, () => {
            logic.actions.removeApp('system:settings')
            logic.actions.installApp('system:notebooks')
        }).toFinishAllListeners()

        expect(writes).toEqual([])
        expect(logic.values.pendingKeys).toEqual(new Set())
    })
})
