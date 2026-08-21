import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { UUIDT } from '~/common/utils/utils'
import { resetTestDatabase } from '~/tests/helpers/sql'
import { Hub, Team } from '~/types'

import { PostgresPersonRepository } from './postgres-person-repository'
import { TEST_TIMESTAMP, getFirstTeam } from './test-helpers'

jest.mock('~/common/utils/logger')

// Runs against the tracked schema, which declares posthog_person_new_uuid_idx UNIQUE. That
// index is what turns a uuid collision into a failed write, so these tests need it and must
// not mutate it. Production does not have it yet, which is why the collision there produces a
// duplicate row instead and this recovery path is dormant until the index rollout.

describe('PostgresPersonRepository uuid conflict', () => {
    let hub: Hub
    let postgres: PostgresRouter
    let repository: PostgresPersonRepository
    let team: Team

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase()
        postgres = hub.postgres
        repository = new PostgresPersonRepository(postgres, { calculatePropertiesSize: 0 })
        team = await getFirstTeam(postgres)
    })

    afterEach(async () => {
        await closeHub(hub)
        jest.clearAllMocks()
    })

    function createPerson(uuid: string, distinctId: string) {
        return repository.createPerson(TEST_TIMESTAMP, {}, {}, {}, team.id, null, false, uuid, { distinctId })
    }

    it('returns the row holding the uuid so the caller can resolve to it', async () => {
        // The holder owns a different distinct ID, so recovering by distinct ID finds nothing.
        // Carrying the holder is what keeps this from becoming a non-retriable error that
        // stalls the consumer on uncommitted offsets.
        const uuid = new UUIDT().toString()
        const holder = await createPerson(uuid, 'holder-distinct-id')
        expect(holder.success).toBe(true)
        if (!holder.success) {
            return
        }

        const conflicted = await createPerson(uuid, 'a-different-distinct-id')
        expect(conflicted.success).toBe(false)
        if (conflicted.success) {
            return
        }
        expect(conflicted.error).toBe('CreationConflict')
        if (conflicted.error !== 'CreationConflict') {
            return
        }
        expect(conflicted.conflictingPerson?.id).toBe(holder.person.id)
        expect(conflicted.conflictingPerson?.uuid).toBe(uuid)
    })

    it('leaves the holder untouched when a create loses the key', async () => {
        const uuid = new UUIDT().toString()
        const holder = await createPerson(uuid, 'holder-distinct-id')
        expect(holder.success).toBe(true)
        if (!holder.success) {
            return
        }

        await createPerson(uuid, 'a-different-distinct-id')

        const { rows } = await postgres.query(
            PostgresUse.PERSONS_WRITE,
            `SELECT count(*)::int AS n FROM posthog_person WHERE team_id = $1 AND uuid = $2`,
            [team.id, uuid],
            'countHolders'
        )
        expect(rows[0].n).toBe(1)
    })
})
