import { defaultConfig } from '~/common/config/config'
import { KAFKA_COHORT_MEMBERSHIP_CHANGED } from '~/common/config/kafka-topics'
import { KafkaProducer, TopicMessage } from '~/common/kafka/producer'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { parseJSON } from '~/common/utils/json-parse'
import { UUIDT } from '~/common/utils/utils'

import { resetBehavioralCohortsDatabase } from '../../../../tests/helpers/sql'
import { CohortMembershipBackfill } from './membership-backfill'

describe('CohortMembershipBackfill', () => {
    const TEAM_ID = 4242
    const OTHER_TEAM_ID = 4243

    let postgres: PostgresRouter
    let published: TopicMessage[]
    let backfill: CohortMembershipBackfill

    beforeEach(async () => {
        postgres = new PostgresRouter(defaultConfig)
        await resetBehavioralCohortsDatabase(postgres)
        published = []
        const producer = {
            queueMessages: (messages: TopicMessage | TopicMessage[]) => {
                published.push(...(Array.isArray(messages) ? messages : [messages]))
                return Promise.resolve()
            },
        } as unknown as KafkaProducer
        backfill = new CohortMembershipBackfill(postgres, producer)
    })

    afterEach(async () => {
        await postgres.end()
    })

    const insertMembership = async (
        teamId: number,
        cohortId: number,
        inCohort: boolean,
        version: string
    ): Promise<string> => {
        const personId = new UUIDT().toString()
        await postgres.query(
            PostgresUse.BEHAVIORAL_COHORTS_RW,
            `INSERT INTO cohort_membership (team_id, cohort_id, person_id, in_cohort, version)
             VALUES ($1, $2, $3, $4, $5::timestamp)`,
            [teamId, cohortId, personId, inCohort, version],
            'test'
        )
        return personId
    }

    const publishedChanges = (): Record<string, unknown>[] =>
        published
            .flatMap((record) => {
                expect(record.topic).toEqual(KAFKA_COHORT_MEMBERSHIP_CHANGED)
                return record.messages.map((message) => parseJSON(String(message.value)))
            })
            .sort((a, b) => String(a.person_id).localeCompare(String(b.person_id)))

    it.each([
        ['every team', null],
        ['one team', TEAM_ID],
    ])('should publish each member of %s once with its version, across pages', async (_label, teamId) => {
        const member = await insertMembership(TEAM_ID, 1, true, '2026-10-14 08:00:00.123456')
        // A row written before versioning reads as -infinity. ClickHouse stores a change without a
        // version at the epoch, so the backfill row must use the same stamp.
        const preVersioning = await insertMembership(TEAM_ID, 2, true, '-infinity')
        const otherCohort = await insertMembership(TEAM_ID, 3, true, '2026-10-14 09:00:00.000000')
        await insertMembership(TEAM_ID, 1, false, '2026-10-14 08:00:00.000000')
        const otherTeam = await insertMembership(OTHER_TEAM_ID, 1, true, '2026-10-14 10:00:00.000000')

        const expected = [
            { team_id: TEAM_ID, cohort_id: 1, person_id: member, last_updated: '2026-10-14 08:00:00.123456' },
            { team_id: TEAM_ID, cohort_id: 2, person_id: preVersioning, last_updated: '1970-01-01 00:00:00.000000' },
            { team_id: TEAM_ID, cohort_id: 3, person_id: otherCohort, last_updated: '2026-10-14 09:00:00.000000' },
            ...(teamId === null
                ? [
                      {
                          team_id: OTHER_TEAM_ID,
                          cohort_id: 1,
                          person_id: otherTeam,
                          last_updated: '2026-10-14 10:00:00.000000',
                      },
                  ]
                : []),
        ]
            .map((change) => ({ ...change, status: 'entered', origin: 'backfill' }))
            .sort((a, b) => a.person_id.localeCompare(b.person_id))

        // A page smaller than the table makes the keyset cursor advance across pages.
        expect(await backfill.run({ teamId, batchSize: 2, pauseMs: 0 })).toEqual(expected.length)
        expect(publishedChanges()).toEqual(expected)
    })
})
