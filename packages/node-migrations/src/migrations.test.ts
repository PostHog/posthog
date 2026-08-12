import { migrationTableForService } from './migrations.js'

describe('migrationTableForService', () => {
    it.each([
        ['recording-api', 'recording_api_schema_migrations'],
        ['mcp', 'mcp_schema_migrations'],
        ['service2', 'service2_schema_migrations'],
    ])('maps %s to %s', (serviceName, tableName) => {
        expect(migrationTableForService(serviceName)).toBe(tableName)
    })

    it.each(['Uppercase', 'has_spaces', '-leading', 'trailing-'])('rejects unsafe service name %s', (serviceName) => {
        expect(() => migrationTableForService(serviceName)).toThrow(
            'Service name must use lowercase letters, numbers, and hyphens'
        )
    })
})
