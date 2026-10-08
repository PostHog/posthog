import { WAREHOUSE_ITEMS, isWarehouseToolHref, warehouseItemForLocation } from './todayWarehouseItems'

describe('todayWarehouseItems', () => {
    test.each([
        ['/sql', 'sql_editor'],
        ['/data-management/sources/abc/schemas', 'sources'],
        ['/models', 'models'],
        ['/models/abc', 'models'],
        ['/warehouse', 'home'],
        ['/data-warehouse/new-source', null],
        ['/insights/abc', null],
        ['/data-management/properties/abc', 'definitions'],
        ['/data-management/events', 'definitions'],
        ['/pipeline/batch-exports/abc', 'destinations'],
        ['/data-management/ingestion-warnings-v2', 'ingestion_warnings'],
        ['/endpoints/my-endpoint', 'endpoints'],
        ['/bi', null],
        ['/data-management/annotations', null],
    ])('marks %s as %s', (path, key) => {
        expect(warehouseItemForLocation(path, WAREHOUSE_ITEMS)?.key ?? null).toBe(key)
    })

    test.each([
        ['/sql', true],
        ['/data-catalog', true],
        ['/data-management/variables', true],
        ['/sql?open_query=abc', true],
        ['/etl', true],
        ['/data-management/destinations?tab=all', true],
        ['/bi', false],
        ['/data-management/schema', true],
        ['/data-management/annotations', false],
    ])('treats the %s tool as a warehouse tool: %s', (href, expected) => {
        expect(isWarehouseToolHref(href)).toBe(expected)
    })
})
