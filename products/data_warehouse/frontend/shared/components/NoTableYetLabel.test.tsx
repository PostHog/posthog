import { waitsOnApple } from './NoTableYetLabel'

describe('waitsOnApple', () => {
    it.each([
        ['an App Store Connect analytics report', 'AppStoreConnect', 'analytics_app_sessions', true],
        ['an App Store Connect sales report', 'AppStoreConnect', 'sales_reports', false],
        ['an App Store Connect metadata table', 'AppStoreConnect', 'apps', false],
        ['a schema with no name', 'AppStoreConnect', undefined, false],
        ['another source', 'Stripe', 'analytics_anything', false],
    ] as const)('%s -> %s', (_name, sourceType, schemaName, expected) => {
        expect(waitsOnApple({ sourceType, schemaName })).toBe(expected)
    })
})
