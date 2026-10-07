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
    ])('marks %s as %s', (path, key) => {
        expect(warehouseItemForLocation(path, WAREHOUSE_ITEMS)?.key ?? null).toBe(key)
    })

    test.each([
        ['/sql', true],
        ['/data-catalog', true],
        ['/data-management/variables', true],
        ['/sql?open_query=abc', true],
        ['/etl', false],
        ['/data-management/destinations?tab=all', false],
    ])('treats the %s tool as a warehouse tool: %s', (href, expected) => {
        expect(isWarehouseToolHref(href)).toBe(expected)
    })
})
