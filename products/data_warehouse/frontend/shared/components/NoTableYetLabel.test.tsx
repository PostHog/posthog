import { ExternalDataSourceTypeEnumApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { waitsOnApple } from './NoTableYetLabel'

const cases: [string, ExternalDataSourceTypeEnumApi, string | undefined, boolean][] = [
    ['an App Store Connect analytics report', 'AppStoreConnect', 'analytics_app_sessions', true],
    ['an App Store Connect sales report', 'AppStoreConnect', 'sales_reports', false],
    ['an App Store Connect metadata table', 'AppStoreConnect', 'apps', false],
    ['a schema with no name', 'AppStoreConnect', undefined, false],
    ['another source', 'Stripe', 'analytics_anything', false],
]

describe('waitsOnApple', () => {
    it.each(cases)('%s -> %s', (_name, sourceType, schemaName, expected) => {
        expect(waitsOnApple({ sourceType, schemaName })).toBe(expected)
    })
})
