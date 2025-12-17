import { DatabaseSchemaTable } from '~/queries/schema/schema-general'

import { buildCreateTableStatement } from './biLogic'

describe('buildCreateTableStatement', () => {
    it('aligns columns and types and skips simple expressions', () => {
        const table = {
            type: 'posthog',
            id: 'postgres.posthog_dashboard',
            name: 'postgres.posthog_dashboard',
            source: {
                id: 'eb101f0d-955d-4f08-8ffa-09c68edcdb36',
                status: 'ok',
                source_type: 'Postgres',
                prefix: 'postgres',
            },
            fields: {
                id: { name: 'id', hogql_value: 'id', type: 'integer', schema_valid: true },
                name: { name: 'name', hogql_value: 'name', type: 'string', schema_valid: true },
                created_by_id: {
                    name: 'created_by_id',
                    hogql_value: 'created_by_id',
                    type: 'integer',
                    schema_valid: true,
                },
                team_id: { name: 'team_id', hogql_value: 'team_id', type: 'integer', schema_valid: true },
                computed: { name: 'computed', hogql_value: '2 * amount', type: 'integer', schema_valid: true },
            },
            schema_metadata: {
                primary_key: ['id'],
                foreign_keys: [
                    { column: 'created_by_id', target_table: 'postgres.posthog_user', target_column: 'id' },
                    { column: 'team_id', target_table: 'postgres.posthog_team', target_column: 'id' },
                ],
            },
        } as unknown as DatabaseSchemaTable

        const statement = buildCreateTableStatement(table, null)

        expect(statement).toEqual(`USE CONNECTION eb101f0d-955d-4f08-8ffa-09c68edcdb36
CREATE TABLE "postgres"."posthog_dashboard" {
    "id"            integer,
    "computed"      integer        expr 2 * amount,
    "created_by_id" integer hidden,
    "name"          string,
    "team_id"       integer hidden,
    "created_by"    connect        "created_by_id" to "postgres.posthog_user"."id",
    "team"          connect        "team_id" to "postgres.posthog_team"."id"
}`)
    })
})
