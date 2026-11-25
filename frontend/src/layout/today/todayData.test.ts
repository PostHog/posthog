import { FEATURE_FLAGS } from 'lib/constants'

import { DATA_PANE } from './todayData'
import { isPaneProductShown, paneConfigProductForPath, paneProducts } from './todayPaneProducts'

const CONSOLE_ROWS = [
    ['warehouse-posthog-data', 'PostHog data', '/warehouse/posthog-data'],
    ['warehouse-source-data', 'Source data', '/warehouse/source-data'],
    ['warehouse-usage', 'Usage', '/warehouse/usage'],
    ['warehouse-queries', 'Queries', '/warehouse/queries'],
    ['warehouse-storage', 'Storage', '/warehouse/storage'],
    ['warehouse-access', 'Access', '/warehouse/access'],
    ['warehouse-connect', 'Connect', '/warehouse/connect'],
    ['warehouse-settings', 'Settings', '/warehouse/settings'],
] as const

function shownWarehouseKeys(flags: Record<string, boolean>): string[] {
    const warehouse = paneProducts(DATA_PANE).sections.find(({ section }) => section.id === 'warehouse')
    return (warehouse?.products ?? []).filter((product) => isPaneProductShown(product, flags)).map(({ key }) => key)
}

describe('the warehouse section of the Data pane', () => {
    it('lists the console pages after the existing rows, and only with the console flag on', () => {
        const flags = { [FEATURE_FLAGS.MANAGED_WAREHOUSE_CONSOLE]: true }
        const consoleKeys = CONSOLE_ROWS.map(([key]) => key)

        expect(shownWarehouseKeys(flags).slice(-consoleKeys.length)).toEqual(consoleKeys)
        expect(shownWarehouseKeys({}).filter((key) => consoleKeys.includes(key as never))).toEqual([])
    })

    it.each([
        [false, true],
        [true, false],
    ])('with the console flag %s, Data ops shows: %s', (consoleOn, dataOpsShown) => {
        const flags = {
            [FEATURE_FLAGS.DATA_WAREHOUSE_SCENE]: true,
            [FEATURE_FLAGS.MANAGED_WAREHOUSE_CONSOLE]: consoleOn,
        }
        expect(shownWarehouseKeys(flags).includes('data_warehouse')).toBe(dataOpsShown)
    })

    const pathRows: [string, string, string][] = [
        ...CONSOLE_ROWS.map(([key, label, path]): [string, string, string] => [path, key, label]),
        ['/warehouse', 'warehouse-settings', 'Settings'],
    ]

    it.each(pathRows)('opens %s on the %s row, labeled %s', (path, key, label) => {
        const product = paneConfigProductForPath(DATA_PANE, path)

        expect(product?.key).toBe(key)
        expect(product?.label).toBe(label)
    })

    it('keeps the Data ops path on the Data ops row', () => {
        expect(paneConfigProductForPath(DATA_PANE, '/data-ops')?.key).toBe('data_warehouse')
    })
})
