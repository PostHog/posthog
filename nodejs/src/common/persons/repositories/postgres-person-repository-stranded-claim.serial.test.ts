// Serial: drops and recreates a shared PostgreSQL index.
import { DateTime } from 'luxon'

import { PERSONS_OUTPUT, PERSON_DISTINCT_IDS_OUTPUT } from '~/common/outputs/persons'
import { personCreateStrandedClaimCounter } from '~/common/persons/metrics'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { parseJSON } from '~/common/utils/json-parse'
import { UUIDT } from '~/common/utils/utils'
import { resetTestDatabase } from '~/tests/helpers/sql'
import { Hub, Team } from '~/types'

import { PostgresPersonRepository } from './postgres-person-repository'
import { TEST_TIMESTAMP, fetchDistinctIdValues, getFirstTeam } from './test-helpers'

jest.mock('~/common/utils/logger')

// Production does NOT have the unique (team_id, uuid) index the tracked schema declares
// (posthog_person_new_uuid_idx is non-unique in both prod regions), which is what lets
// duplicate persons exist there at all. The tests below recreate that reality; with the
// tracked schema's unique index in place, the duplicate scenarios cannot even be seeded
// and every claim test would pass vacuously.
async function makeUuidIndexNonUnique(postgres: PostgresRouter): Promise<void> {
    const { rows } = await postgres.query(
        PostgresUse.PERSONS_WRITE,
        `SELECT i.indisunique FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
         WHERE c.relname = 'posthog_person_new_uuid_idx'`,
        [],
        'checkUuidIndex'
    )
    if (rows.length > 0 && !rows[0].indisunique) {
        return
    }
    await postgres.query(PostgresUse.PERSONS_WRITE, `DROP INDEX IF EXISTS posthog_person_new_uuid_idx`, [], 'dropIdx')
    await postgres.query(
        PostgresUse.PERSONS_WRITE,
        `CREATE INDEX posthog_person_new_uuid_idx ON posthog_person (team_id, uuid)`,
        [],
        'createIdx'
    )
}

async function restoreUniqueUuidIndex(postgres: PostgresRouter): Promise<void> {
    // The last test leaves duplicate (team_id, uuid) rows behind; clear them or the
    // unique index cannot build.
    await postgres.query(PostgresUse.PERSONS_WRITE, `DELETE FROM posthog_persondistinctid`, [], 'clearPdi')
    await postgres.query(PostgresUse.PERSONS_WRITE, `DELETE FROM posthog_person`, [], 'clearPersons')
    await postgres.query(PostgresUse.PERSONS_WRITE, `DROP INDEX IF EXISTS posthog_person_new_uuid_idx`, [], 'dropIdx')
    await postgres.query(
        PostgresUse.PERSONS_WRITE,
        `CREATE UNIQUE INDEX posthog_person_new_uuid_idx ON posthog_person (team_id, uuid)`,
        [],
        'createIdx'
    )
}

describe('PostgresPersonRepository stranded-row claim', () => {
    let hub: Hub
    let postgres: PostgresRouter
    let repository: PostgresPersonRepository
    let team: Team

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase()
        postgres = hub.postgres
        await makeUuidIndexNonUnique(postgres)
        repository = new PostgresPersonRepository(postgres, {
            calculatePropertiesSize: 0,
            personCreateClaimTeamAllowlist: '*',
        })
        team = await getFirstTeam(postgres)
        personCreateStrandedClaimCounter.reset()
    })

    afterEach(async () => {
        await closeHub(hub)
        jest.clearAllMocks()
    })

    afterAll(async () => {
        // Other suites share this worker's database and expect the tracked schema.
        const cleanupHub = await createHub()
        await restoreUniqueUuidIndex(cleanupHub.postgres)
        await closeHub(cleanupHub)
    })

    // A person row with no distinct-ID mapping, the way rows stranded by out-of-band
    // mapping deletion look in production.
    async function seedStrandedPerson(
        teamId: number,
        uuid: string,
        overrides: {
            version?: number
            properties?: Record<string, any>
            isIdentified?: boolean
            isDeleted?: boolean
        } = {}
    ): Promise<number> {
        const { rows } = await postgres.query(
            PostgresUse.PERSONS_WRITE,
            `INSERT INTO posthog_person (
                created_at, properties, properties_last_updated_at, properties_last_operation,
                team_id, is_user_id, is_identified, uuid, version, is_deleted
            ) VALUES ($1, $2, '{}', '{}', $3, NULL, $4, $5, $6, $7) RETURNING id`,
            [
                DateTime.fromISO('2023-06-01T00:00:00.000Z').toISO(),
                JSON.stringify(overrides.properties ?? { stale: 'value' }),
                teamId,
                overrides.isIdentified ?? false,
                uuid,
                overrides.version ?? 3,
                overrides.isDeleted ?? false,
            ],
            'seedStrandedPerson'
        )
        return Number(rows[0].id)
    }

    async function addMapping(teamId: number, personId: number, distinctId: string, isDeleted = false): Promise<void> {
        await postgres.query(
            PostgresUse.PERSONS_WRITE,
            `INSERT INTO posthog_persondistinctid (distinct_id, person_id, team_id, version, is_deleted)
             VALUES ($1, $2, $3, 0, $4)`,
            [distinctId, personId, teamId, isDeleted],
            'seedMapping'
        )
    }

    async function fetchPersonRows(teamId: number, uuid: string): Promise<{ id: number; version: number }[]> {
        const { rows } = await postgres.query(
            PostgresUse.PERSONS_WRITE,
            `SELECT id, version FROM posthog_person WHERE team_id = $1 AND uuid = $2 ORDER BY id`,
            [teamId, uuid],
            'fetchPersonRows'
        )
        return rows.map((r: any) => ({ id: Number(r.id), version: Number(r.version) }))
    }

    async function createPerson(
        uuid: string,
        distinctId: string,
        properties: Record<string, any> = {}
    ): ReturnType<PostgresPersonRepository['createPerson']> {
        return await repository.createPerson(TEST_TIMESTAMP, properties, {}, {}, team.id, null, true, uuid, {
            distinctId,
        })
    }

    async function getCounterValue(outcome: string): Promise<number> {
        const metric = await personCreateStrandedClaimCounter.get()
        return metric.values.find((v) => v.labels.outcome === outcome)?.value ?? 0
    }

    it('the fixture allows duplicate (team_id, uuid) rows, like production', async () => {
        const uuid = new UUIDT().toString()
        await seedStrandedPerson(team.id, uuid)
        // With the tracked schema's unique index this second insert would throw, and
        // every scenario below would be untestable.
        await expect(seedStrandedPerson(team.id, uuid)).resolves.toEqual(expect.any(Number))
    })

    it('claims the stranded row: same row id, reset properties, bumped version, new mapping', async () => {
        const uuid = new UUIDT().toString()
        const strandedId = await seedStrandedPerson(team.id, uuid, { version: 7, properties: { stale: 'yes' } })

        const result = await createPerson(uuid, 'returning-user', { fresh: 'yes' })

        expect(result.success).toBe(true)
        if (!result.success) {
            return
        }
        expect(result.created).toBe(true)
        expect(Number(result.person.id)).toBe(strandedId)
        expect(result.person.uuid).toBe(uuid)
        expect(result.person.properties).toEqual({ fresh: 'yes' })
        expect(result.person.version).toBe(8)
        expect(result.person.is_identified).toBe(true)

        // Exactly one row holds the uuid, and the mapping points at it.
        expect(await fetchPersonRows(team.id, uuid)).toEqual([{ id: strandedId, version: 8 }])
        expect(await fetchDistinctIdValues(postgres, result.person)).toEqual(['returning-user'])
        expect(await getCounterValue('claimed')).toBe(1)
    })

    it('emits the person update and the distinct-id mapping to Kafka on a claim', async () => {
        const uuid = new UUIDT().toString()
        await seedStrandedPerson(team.id, uuid)

        const result = await createPerson(uuid, 'returning-user')
        expect(result.success).toBe(true)
        if (!result.success) {
            return
        }

        const personMessages = result.messages.filter((m) => m.output === PERSONS_OUTPUT)
        const didMessages = result.messages.filter((m) => m.output === PERSON_DISTINCT_IDS_OUTPUT)
        expect(personMessages).toHaveLength(1)
        expect(didMessages).toHaveLength(1)

        const didPayload = parseJSON(didMessages[0].value!.toString())
        expect(didPayload).toEqual({
            person_id: uuid,
            team_id: team.id,
            distinct_id: 'returning-user',
            // Version 0 keeps the mapping out of the ClickHouse overrides view: events
            // stamped with this deterministic uuid already point at the right person.
            version: 0,
            is_deleted: 0,
        })
    })

    it('claims exactly one row (the oldest) when several stranded rows share the uuid', async () => {
        const uuid = new UUIDT().toString()
        const olderId = await seedStrandedPerson(team.id, uuid, { version: 1 })
        const newerId = await seedStrandedPerson(team.id, uuid, { version: 5 })

        const result = await createPerson(uuid, 'returning-user')
        expect(result.success).toBe(true)
        if (!result.success) {
            return
        }

        expect(Number(result.person.id)).toBe(olderId)
        const rows = await fetchPersonRows(team.id, uuid)
        // The newer stranded row is untouched; repair tooling owns it.
        expect(rows).toEqual([
            { id: olderId, version: 2 },
            { id: newerId, version: 5 },
        ])
        expect(await getCounterValue('claimed')).toBe(1)
    })

    it('never claims a row the product can still reach', async () => {
        const uuid = new UUIDT().toString()
        const reachableId = await seedStrandedPerson(team.id, uuid, { version: 4 })
        await addMapping(team.id, reachableId, 'other-distinct-id')

        const result = await createPerson(uuid, 'second-distinct-id')
        expect(result.success).toBe(true)
        if (!result.success) {
            return
        }

        // Pre-existing behavior for this (bounded, known) case: a duplicate row is
        // created rather than ingestion failing. The metric is the alarm.
        expect(Number(result.person.id)).not.toBe(reachableId)
        const rows = await fetchPersonRows(team.id, uuid)
        expect(rows).toHaveLength(2)
        expect(rows[0]).toEqual({ id: reachableId, version: 4 })
        expect(await getCounterValue('inserted_duplicate')).toBe(1)
        expect(await getCounterValue('claimed')).toBe(0)
    })

    it('treats a row whose only mapping is soft-deleted as claimable', async () => {
        const uuid = new UUIDT().toString()
        const strandedId = await seedStrandedPerson(team.id, uuid)
        await addMapping(team.id, strandedId, 'dead-distinct-id', true)

        const result = await createPerson(uuid, 'live-distinct-id')
        expect(result.success).toBe(true)
        if (!result.success) {
            return
        }

        expect(Number(result.person.id)).toBe(strandedId)
        expect(await getCounterValue('claimed')).toBe(1)
    })

    it('never claims a tombstoned (is_deleted) row: falls through to a fresh insert', async () => {
        const uuid = new UUIDT().toString()
        const tombstonedId = await seedStrandedPerson(team.id, uuid, { version: 6, isDeleted: true })

        const result = await createPerson(uuid, 'returning-user')
        expect(result.success).toBe(true)
        if (!result.success) {
            return
        }

        // The tombstoned row is not revived; the create behaves as if it were absent.
        expect(Number(result.person.id)).not.toBe(tombstonedId)
        expect(result.person.version).toBe(0)
        expect(await fetchPersonRows(team.id, uuid)).toEqual([
            { id: tombstonedId, version: 6 },
            { id: Number(result.person.id), version: 0 },
        ])
        expect(await getCounterValue('claimed')).toBe(0)
        expect(await getCounterValue('inserted')).toBe(1)
    })

    it('claims with extra distinct IDs: every mapping lands on the claimed row', async () => {
        const uuid = new UUIDT().toString()
        const strandedId = await seedStrandedPerson(team.id, uuid)

        const result = await repository.createPerson(
            TEST_TIMESTAMP,
            {},
            {},
            {},
            team.id,
            null,
            true,
            uuid,
            { distinctId: 'primary-id' },
            [{ distinctId: 'extra-id', version: 2 }]
        )
        expect(result.success).toBe(true)
        if (!result.success) {
            return
        }

        expect(Number(result.person.id)).toBe(strandedId)
        expect((await fetchDistinctIdValues(postgres, result.person)).sort()).toEqual(['extra-id', 'primary-id'])

        const didPayloads = result.messages
            .filter((m) => m.output === PERSON_DISTINCT_IDS_OUTPUT)
            .map((m) => parseJSON(m.value!.toString()))
        expect(didPayloads).toEqual(
            expect.arrayContaining([
                expect.objectContaining({ distinct_id: 'primary-id', version: 0, person_id: uuid }),
                expect.objectContaining({ distinct_id: 'extra-id', version: 2, person_id: uuid }),
            ])
        )
        expect(didPayloads).toHaveLength(2)
        expect(await getCounterValue('claimed')).toBe(1)
    })

    it('inserts normally when nothing holds the uuid', async () => {
        const uuid = new UUIDT().toString()
        const result = await createPerson(uuid, 'brand-new-user', { a: 1 })

        expect(result.success).toBe(true)
        if (!result.success) {
            return
        }
        expect(result.created).toBe(true)
        expect(result.person.uuid).toBe(uuid)
        expect(result.person.version).toBe(0)
        expect(await fetchDistinctIdValues(postgres, result.person)).toEqual(['brand-new-user'])
        expect(await getCounterValue('inserted')).toBe(1)
        expect(await getCounterValue('claimed')).toBe(0)
    })

    it('returns CreationConflict when the distinct ID is already mapped', async () => {
        const uuid = new UUIDT().toString()
        const first = await createPerson(uuid, 'contested-distinct-id')
        expect(first.success).toBe(true)

        // Same repository-level contract as the legacy path: the caller resolves the
        // conflict by re-fetching the person by distinct ID.
        const second = await createPerson(new UUIDT().toString(), 'contested-distinct-id')
        expect(second.success).toBe(false)
        if (second.success) {
            return
        }
        expect(second.error).toBe('CreationConflict')
    })

    it('does not claim for teams outside the allowlist', async () => {
        const legacyRepository = new PostgresPersonRepository(postgres, {
            calculatePropertiesSize: 0,
            // personCreateClaimTeamAllowlist deliberately unset
        })
        const uuid = new UUIDT().toString()
        const strandedId = await seedStrandedPerson(team.id, uuid)

        const result = await legacyRepository.createPerson(TEST_TIMESTAMP, {}, {}, {}, team.id, null, true, uuid, {
            distinctId: 'returning-user',
        })
        expect(result.success).toBe(true)
        if (!result.success) {
            return
        }

        // Legacy behavior preserved: a duplicate row, the stranded one untouched.
        expect(Number(result.person.id)).not.toBe(strandedId)
        expect(await fetchPersonRows(team.id, uuid)).toHaveLength(2)
        expect(await getCounterValue('claimed')).toBe(0)
        expect(await getCounterValue('inserted')).toBe(0)
    })
})
