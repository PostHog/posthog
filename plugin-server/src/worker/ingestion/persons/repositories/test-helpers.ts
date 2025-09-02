import fs from 'fs'
import { DateTime } from 'luxon'
import path from 'path'

import { Hub, InternalPerson, PersonDistinctId, RawPerson, Team } from '~/types'
import { PostgresRouter, PostgresUse } from '~/utils/db/postgres'

import { CreatePersonResult } from '../../../../utils/db/db'

export const TEST_UUIDS = {
    single: '11111111-1111-1111-1111-111111111111',
    dual: '22222222-2222-2222-2222-222222222222',
}

export const TEST_TIMESTAMP = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()

export async function setupMigrationDb(migrationPostgres: PostgresRouter): Promise<void> {
    const drops = [
        'posthog_featureflaghashkeyoverride',
        'posthog_cohortpeople',
        'posthog_persondistinctid',
        'posthog_personlessdistinctid',
        'posthog_person',
    ]
    for (const table of drops) {
        await migrationPostgres.query(
            PostgresUse.PERSONS_WRITE,
            `DROP TABLE IF EXISTS ${table} CASCADE`,
            [],
            `drop-${table}`
        )
    }
    const sqlPath = path.resolve(__dirname, '../../../../../sql/create_persons_tables.sql')
    const sql = fs.readFileSync(sqlPath, 'utf8')
    await migrationPostgres.query(PostgresUse.PERSONS_WRITE, sql, [], 'create-persons-schema-secondary')
}

export async function cleanupPrepared(hub: Hub) {
    const routers = [hub.db.postgres, hub.db.postgresPersonMigration]
    for (const r of routers) {
        const res = await r.query(
            PostgresUse.PERSONS_WRITE,
            `SELECT gid FROM pg_prepared_xacts WHERE gid LIKE 'dualwrite:%'`,
            [],
            'list-prepared'
        )
        for (const row of res.rows) {
            await r.query(
                PostgresUse.PERSONS_WRITE,
                `ROLLBACK PREPARED '${String(row.gid).replace(/'/g, "''")}'`,
                [],
                'rollback-prepared'
            )
        }
    }
}

export async function getFirstTeam(postgres: PostgresRouter): Promise<Team> {
    const teams = await postgres.query(
        PostgresUse.COMMON_WRITE,
        'SELECT * FROM posthog_team LIMIT 1',
        [],
        'getFirstTeam'
    )
    return teams.rows[0]
}

export async function assertConsistencyAcrossDatabases(
    primaryRouter: PostgresRouter,
    secondaryRouter: PostgresRouter,
    query: string,
    params: any[],
    primaryTag: string,
    secondaryTag: string
) {
    const [primary, secondary] = await Promise.all([
        primaryRouter.query(PostgresUse.PERSONS_READ, query, params, primaryTag),
        secondaryRouter.query(PostgresUse.PERSONS_READ, query, params, secondaryTag),
    ])
    expect(primary.rows).toEqual(secondary.rows)
}

export function mockDatabaseError(
    router: PostgresRouter,
    error: Error | { message: string; code?: string; constraint?: string },
    tagPattern: string | RegExp
) {
    const originalQuery = router.query.bind(router)
    return jest.spyOn(router, 'query').mockImplementation((use: any, text: any, params: any, tag: string) => {
        const shouldThrow =
            typeof tagPattern === 'string' ? tag && tag.startsWith(tagPattern) : tag && tagPattern.test(tag)

        if (shouldThrow) {
            if (error instanceof Error) {
                throw error
            } else {
                const e: any = new Error(error.message)
                if (error.code) {
                    e.code = error.code
                }
                if ((error as any).constraint) {
                    e.constraint = (error as any).constraint
                }
                throw e
            }
        }
        return originalQuery(use, text, params, tag)
    })
}

export async function assertConsistentDatabaseErrorHandling<T>(
    postgres: PostgresRouter,
    error: Error | { message: string; code?: string; constraint?: string },
    tagPattern: string | RegExp,
    singleWriteOperation: () => Promise<T>,
    dualWriteOperation: () => Promise<T>,
    expectedError?: string | RegExp | ErrorConstructor
) {
    const singleSpy = mockDatabaseError(postgres, error, tagPattern)
    let singleError: any
    try {
        await singleWriteOperation()
    } catch (e) {
        singleError = e
    }
    singleSpy.mockRestore()

    const dualSpy = mockDatabaseError(postgres, error, tagPattern)
    let dualError: any
    try {
        await dualWriteOperation()
    } catch (e) {
        dualError = e
    }
    dualSpy.mockRestore()

    if (expectedError) {
        expect(singleError).toBeDefined()
        expect(dualError).toBeDefined()

        if (typeof expectedError === 'string') {
            expect(singleError.message).toContain(expectedError)
            expect(dualError.message).toContain(expectedError)
        } else if (expectedError instanceof RegExp) {
            expect(singleError.message).toMatch(expectedError)
            expect(dualError.message).toMatch(expectedError)
        } else {
            expect(singleError).toBeInstanceOf(expectedError)
            expect(dualError).toBeInstanceOf(expectedError)
        }
    } else {
        expect(singleError).toBeDefined()
        expect(dualError).toBeDefined()
        expect(singleError.message).toBe(dualError.message)
        if ((error as any).code) {
            expect(singleError.code).toBe((error as any).code)
            expect(dualError.code).toBe((error as any).code)
        }
        if ((error as any).constraint) {
            expect(singleError.constraint).toBe((error as any).constraint)
            expect(dualError.constraint).toBe((error as any).constraint)
        }
    }
}

export function assertCreatePersonContractParity(singleResult: CreatePersonResult, dualResult: CreatePersonResult) {
    expect(singleResult.success).toBe(true)
    expect(dualResult.success).toBe(true)
    if (singleResult.success && dualResult.success) {
        expect(singleResult.person.properties).toEqual(dualResult.person.properties)
    }
}

export function assertCreatePersonConflictContractParity(
    singleResult: CreatePersonResult,
    dualResult: CreatePersonResult
) {
    expect(singleResult.success).toBe(false)
    expect(dualResult.success).toBe(false)
    if (!singleResult.success && !dualResult.success) {
        expect(singleResult.error).toBe(dualResult.error)
        expect(singleResult.distinctIds).toEqual(dualResult.distinctIds)
    }
}

/**
 * Testing utilities for person-related database operations.
 * These methods are only used in tests and should not be used in production code.
 */

export async function fetchPersons(postgres: PostgresRouter): Promise<InternalPerson[]> {
    return await postgres
        .query<RawPerson>(PostgresUse.PERSONS_WRITE, 'SELECT * FROM posthog_person', undefined, 'fetchPersons')
        .then(({ rows }) => rows.map(toPerson))
}

export async function fetchDistinctIds(postgres: PostgresRouter, person: InternalPerson): Promise<PersonDistinctId[]> {
    const result = await postgres.query(
        PostgresUse.PERSONS_WRITE, // used in tests only
        'SELECT * FROM posthog_persondistinctid WHERE person_id=$1 AND team_id=$2 ORDER BY id',
        [person.id, person.team_id],
        'fetchDistinctIds'
    )
    return result.rows as PersonDistinctId[]
}

export async function fetchDistinctIdValues(postgres: PostgresRouter, person: InternalPerson): Promise<string[]> {
    const personDistinctIds = await fetchDistinctIds(postgres, person)
    return personDistinctIds.map((pdi) => pdi.distinct_id)
}

function toPerson(row: RawPerson): InternalPerson {
    return {
        ...row,
        id: String(row.id),
        created_at: DateTime.fromISO(row.created_at).toUTC(),
        version: Number(row.version || 0),
    }
}
