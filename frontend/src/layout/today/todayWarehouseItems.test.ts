import { FEATURE_FLAGS } from 'lib/constants'

import {
    WAREHOUSE_ITEMS,
    isWarehouseToolHref,
    visibleWarehouseItems,
    warehouseItemForLocation,
} from './todayWarehouseItems'

describe('todayWarehouseItems', () => {
    test.each([
        [{ [FEATURE_FLAGS.DATA_WAREHOUSE_SCENE]: true }, true],
        [{ [FEATURE_FLAGS.MANAGED_TRINO_QUERY]: true }, true],
        [{}, false],
    ])('with flags %j, lists Data ops: %s', (featureFlags, listed) => {
        expect(visibleWarehouseItems(featureFlags).some((item) => item.key === 'data_ops')).toBe(listed)
    })

    const MANAGE_KEYS = ['data_ops', 'usage', 'queries', 'storage', 'access', 'connect', 'settings']

    test.each([
        [
            { [FEATURE_FLAGS.MANAGED_WAREHOUSE_CONSOLE]: true, [FEATURE_FLAGS.DATA_WAREHOUSE_SCENE]: true },
            ['usage', 'queries', 'storage', 'access', 'connect', 'settings'],
        ],
        [{ [FEATURE_FLAGS.DATA_WAREHOUSE_SCENE]: true }, ['data_ops']],
        [{ [FEATURE_FLAGS.MANAGED_TRINO_QUERY]: true }, ['data_ops']],
    ])('with flags %j, lists the Manage pages %j', (featureFlags, listed) => {
        const keys = visibleWarehouseItems(featureFlags).map((item) => item.key)
        expect(keys.filter((key) => MANAGE_KEYS.includes(key))).toEqual(listed)
    })

    test.each([
        ['/sql', 'sql_editor'],
        ['/data-management/sources/abc/schemas', null],
        ['/models', 'models'],
        ['/models/abc', 'models'],
        ['/warehouse', 'home'],
        ['/warehouse/posthog-data', 'posthog_data'],
        ['/warehouse/source-data', 'source_data'],
        ['/warehouse/usage', 'usage'],
        ['/warehouse/queries', 'queries'],
        ['/warehouse/storage', 'storage'],
        ['/warehouse/access', 'access'],
        ['/warehouse/connect', 'connect'],
        ['/warehouse/settings', 'settings'],
        ['/data-warehouse/new-source', null],
        ['/insights/abc', null],
        ['/endpoints/my-endpoint', null],
        ['/bi', null],
        ['/data-management/annotations', null],
        ['/data-management/events', null],
        ['/data-management/ingestion-warnings', null],
        ['/pipeline/batch-exports/abc', null],
        ['/data-management/destinations', null],
    ])('marks %s as %s', (path, key) => {
        expect(warehouseItemForLocation(path, WAREHOUSE_ITEMS)?.key ?? null).toBe(key)
    })

    test.each([
        ['/models', 'lineage', 'models_lineage'],
        ['/models', null, 'models'],
        // A tab no item names, or a page under the path, falls back to the page's first tab.
        ['/models', 'nonsense', 'models'],
        ['/models/abc', 'lineage', 'models_lineage'],
        ['/data-catalog', 'relationships', 'data_catalog_relationships'],
        ['/data-catalog', null, 'data_catalog'],
        // `tab` belongs to the page it is on, so it does not move another page to one of its tabs.
        ['/warehouse/storage', 'usage', 'storage'],
    ])('marks %s with tab %s as %s', (path, tab, key) => {
        expect(warehouseItemForLocation(path, WAREHOUSE_ITEMS, tab)?.key ?? null).toBe(key)
    })

    test.each([
        ['/sql', true],
        ['/data-catalog', true],
        ['/data-management/sources', false],
        ['/sql?open_query=abc', true],
        ['/etl', false],
        ['/data-management/destinations?tab=all', false],
        ['/data-management/variables', false],
        ['/bi', false],
        ['/data-management/schema', false],
        ['/data-management/annotations', false],
    ])('treats the %s tool as a warehouse tool: %s', (href, expected) => {
        expect(isWarehouseToolHref(href)).toBe(expected)
    })
})
