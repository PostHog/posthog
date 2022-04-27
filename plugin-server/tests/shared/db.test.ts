import { DateTime } from 'luxon'

import { Hub, Person, PropertyOperator, PropertyUpdateOperation, Team } from '../../src/types'
import { CachedPersonData, DB } from '../../src/utils/db/db'
import { createHub } from '../../src/utils/db/hub'
import { RaceConditionError, UUIDT } from '../../src/utils/utils'
import { getFirstTeam, insertRow, resetTestDatabase } from '../helpers/sql'
import { plugin60 } from './../helpers/plugins'
import { createPerson } from './process-event'

jest.mock('../../src/utils/status')

describe('DB', () => {
    let hub: Hub
    let closeServer: () => Promise<void>
    let db: DB

    beforeEach(async () => {
        ;[hub, closeServer] = await createHub()
        await resetTestDatabase()
        db = hub.db
    })

    afterEach(async () => {
        await closeServer()
    })

    const TEAM_ID = 2
    const ACTION_ID = 69
    const ACTION_STEP_ID = 913
    const TIMESTAMP = DateTime.fromISO('2000-10-14T11:42:06.502Z').toUTC()

    test('fetchAllActionsGroupedByTeam', async () => {
        const action = await db.fetchAllActionsGroupedByTeam()

        expect(action).toMatchObject({
            [TEAM_ID]: {
                [ACTION_ID]: {
                    id: ACTION_ID,
                    name: 'Test Action',
                    deleted: false,
                    post_to_slack: true,
                    slack_message_format: '',
                    is_calculating: false,
                    steps: [
                        {
                            id: ACTION_STEP_ID,
                            action_id: ACTION_ID,
                            tag_name: null,
                            text: null,
                            href: null,
                            selector: null,
                            url: null,
                            url_matching: null,
                            name: null,
                            event: null,
                            properties: [
                                { type: 'event', operator: PropertyOperator.Exact, key: 'foo', value: ['bar'] },
                            ],
                        },
                    ],
                },
            },
        })
    })

    async function fetchPersonByPersonId(teamId: number, personId: number): Promise<Person> {
        const selectResult = await db.postgresQuery(
            `SELECT * FROM posthog_person WHERE team_id = $1 AND id = $2`,
            [teamId, personId],
            'fetchPersonByPersonId'
        )

        return selectResult.rows[0]
    }

    describe('createPerson', () => {
        let team: Team
        let person: Person
        const uuid = new UUIDT().toString()
        const distinctId = 'distinct_id1'

        beforeEach(async () => {
            team = await getFirstTeam(hub)
        })

        test('without properties', async () => {
            const person = await db.createPerson(TIMESTAMP, {}, {}, {}, team.id, null, false, uuid, [distinctId])
            const fetched_person = await fetchPersonByPersonId(team.id, person.id)

            expect(fetched_person.is_identified).toEqual(false)
            expect(fetched_person.properties).toEqual({})
            expect(fetched_person.properties_last_operation).toEqual({})
            expect(fetched_person.properties_last_updated_at).toEqual({})
            expect(fetched_person.uuid).toEqual(uuid)
            expect(fetched_person.team_id).toEqual(team.id)
        })

        test('without properties indentified true', async () => {
            const person = await db.createPerson(TIMESTAMP, {}, {}, {}, team.id, null, true, uuid, [distinctId])
            const fetched_person = await fetchPersonByPersonId(team.id, person.id)
            expect(fetched_person.is_identified).toEqual(true)
            expect(fetched_person.properties).toEqual({})
            expect(fetched_person.properties_last_operation).toEqual({})
            expect(fetched_person.properties_last_updated_at).toEqual({})
            expect(fetched_person.uuid).toEqual(uuid)
            expect(fetched_person.team_id).toEqual(team.id)
        })

        test('with properties', async () => {
            const person = await db.createPerson(
                TIMESTAMP,
                { a: 123, b: false, c: 'bbb' },
                { a: TIMESTAMP.toISO(), b: TIMESTAMP.toISO(), c: TIMESTAMP.toISO() },
                { a: PropertyUpdateOperation.Set, b: PropertyUpdateOperation.Set, c: PropertyUpdateOperation.SetOnce },
                team.id,
                null,
                false,
                uuid,
                [distinctId]
            )
            const fetched_person = await fetchPersonByPersonId(team.id, person.id)
            expect(fetched_person.is_identified).toEqual(false)
            expect(fetched_person.properties).toEqual({ a: 123, b: false, c: 'bbb' })
            expect(fetched_person.properties_last_operation).toEqual({
                a: PropertyUpdateOperation.Set,
                b: PropertyUpdateOperation.Set,
                c: PropertyUpdateOperation.SetOnce,
            })
            expect(fetched_person.properties_last_updated_at).toEqual({
                a: TIMESTAMP.toISO(),
                b: TIMESTAMP.toISO(),
                c: TIMESTAMP.toISO(),
            })
            expect(fetched_person.uuid).toEqual(uuid)
            expect(fetched_person.team_id).toEqual(team.id)
        })
    })

    describe('fetchGroupTypes() and insertGroupType()', () => {
        it('fetches group types that have been inserted', async () => {
            expect(await db.fetchGroupTypes(2)).toEqual({})
            expect(await db.insertGroupType(2, 'g0', 0)).toEqual([0, true])
            expect(await db.insertGroupType(2, 'g1', 1)).toEqual([1, true])
            expect(await db.fetchGroupTypes(2)).toEqual({ g0: 0, g1: 1 })
        })

        it('handles conflicting by index when inserting and limits', async () => {
            expect(await db.insertGroupType(2, 'g0', 0)).toEqual([0, true])
            expect(await db.insertGroupType(2, 'g1', 0)).toEqual([1, true])
            expect(await db.insertGroupType(2, 'g2', 0)).toEqual([2, true])
            expect(await db.insertGroupType(2, 'g3', 1)).toEqual([3, true])
            expect(await db.insertGroupType(2, 'g4', 0)).toEqual([4, true])
            expect(await db.insertGroupType(2, 'g5', 0)).toEqual([null, false])
            expect(await db.insertGroupType(2, 'g6', 0)).toEqual([null, false])

            expect(await db.fetchGroupTypes(2)).toEqual({ g0: 0, g1: 1, g2: 2, g3: 3, g4: 4 })
        })

        it('handles conflict by name when inserting', async () => {
            expect(await db.insertGroupType(2, 'group_name', 0)).toEqual([0, true])
            expect(await db.insertGroupType(2, 'group_name', 0)).toEqual([0, false])
            expect(await db.insertGroupType(2, 'group_name', 0)).toEqual([0, false])
            expect(await db.insertGroupType(2, 'foo', 0)).toEqual([1, true])
            expect(await db.insertGroupType(2, 'foo', 0)).toEqual([1, false])

            expect(await db.fetchGroupTypes(2)).toEqual({ group_name: 0, foo: 1 })
        })
    })

    describe('fetchGroup(), insertGroup() and updateGroup()', () => {
        it('returns undefined if no group type exists', async () => {
            await db.insertGroup(
                2,
                0,
                'group_key',
                { prop: 'val' },
                TIMESTAMP,
                { prop: TIMESTAMP.toISO() },
                { prop: PropertyUpdateOperation.Set },
                1
            )

            expect(await db.fetchGroup(3, 0, 'group_key')).toEqual(undefined)
            expect(await db.fetchGroup(2, 1, 'group_key')).toEqual(undefined)
            expect(await db.fetchGroup(2, 1, 'group_key2')).toEqual(undefined)
        })

        it('allows inserts and fetches', async () => {
            await db.insertGroup(
                2,
                0,
                'group_key',
                { prop: 'val' },
                TIMESTAMP,
                { prop: TIMESTAMP.toISO() },
                { prop: PropertyUpdateOperation.Set },
                1
            )

            expect(await db.fetchGroup(2, 0, 'group_key')).toEqual({
                id: expect.any(Number),
                team_id: 2,
                group_type_index: 0,
                group_key: 'group_key',
                group_properties: { prop: 'val' },
                created_at: TIMESTAMP,
                properties_last_updated_at: { prop: TIMESTAMP.toISO() },
                properties_last_operation: { prop: PropertyUpdateOperation.Set },
                version: 1,
            })
        })

        it('insertGroup raises RaceConditionErrors if inserting in parallel', async () => {
            await db.insertGroup(
                2,
                0,
                'group_key',
                { prop: 'val' },
                TIMESTAMP,
                { prop: TIMESTAMP.toISO() },
                { prop: PropertyUpdateOperation.Set },
                1
            )

            await expect(
                db.insertGroup(
                    2,
                    0,
                    'group_key',
                    { prop: 'newval' },
                    TIMESTAMP,
                    { prop: TIMESTAMP.toISO() },
                    { prop: PropertyUpdateOperation.Set },
                    1
                )
            ).rejects.toEqual(new RaceConditionError('Parallel posthog_group inserts, retry'))
        })

        it('handles updates', async () => {
            await db.insertGroup(
                2,
                0,
                'group_key',
                { prop: 'val' },
                TIMESTAMP,
                { prop: TIMESTAMP.toISO() },
                { prop: PropertyUpdateOperation.Set },
                1
            )

            const originalGroup = await db.fetchGroup(2, 0, 'group_key')

            const timestamp2 = DateTime.fromISO('2000-10-14T12:42:06.502Z').toUTC()
            await db.updateGroup(
                2,
                0,
                'group_key',
                { prop: 'newVal', prop2: 2 },
                TIMESTAMP,
                { prop: timestamp2.toISO(), prop2: timestamp2.toISO() },
                { prop: PropertyUpdateOperation.Set, prop2: PropertyUpdateOperation.Set },
                2
            )

            expect(await db.fetchGroup(2, 0, 'group_key')).toEqual({
                id: originalGroup!.id,
                team_id: 2,
                group_type_index: 0,
                group_key: 'group_key',
                group_properties: { prop: 'newVal', prop2: 2 },
                created_at: TIMESTAMP,
                properties_last_updated_at: { prop: timestamp2.toISO(), prop2: timestamp2.toISO() },
                properties_last_operation: { prop: PropertyUpdateOperation.Set, prop2: PropertyUpdateOperation.Set },
                version: 2,
            })
        })
    })

    describe('addOrUpdatePublicJob', () => {
        it('updates the column if the job name is new', async () => {
            await insertRow(db.postgres, 'posthog_plugin', { ...plugin60, id: 88 })

            const jobName = 'newJob'
            const jobPayload = { foo: 'string' }
            await db.addOrUpdatePublicJob(88, jobName, jobPayload)
            const publicJobs = (
                await db.postgresQuery('SELECT public_jobs FROM posthog_plugin WHERE id = $1', [88], 'testPublicJob1')
            ).rows[0].public_jobs

            expect(publicJobs[jobName]).toEqual(jobPayload)
        })

        it('updates the column if the job payload is new', async () => {
            await insertRow(db.postgres, 'posthog_plugin', { ...plugin60, id: 88, public_jobs: { foo: 'number' } })

            const jobName = 'newJob'
            const jobPayload = { foo: 'string' }
            await db.addOrUpdatePublicJob(88, jobName, jobPayload)
            const publicJobs = (
                await db.postgresQuery('SELECT public_jobs FROM posthog_plugin WHERE id = $1', [88], 'testPublicJob1')
            ).rows[0].public_jobs

            expect(publicJobs[jobName]).toEqual(jobPayload)
        })
    })

    describe('getPersonData', () => {
        let cache: Record<string, string> = {}

        beforeEach(() => {
            db.statsd = {
                timing: jest.fn(),
                increment: jest.fn(),
                gauge: jest.fn(),
            } as any

            // mock redis
            cache = {}

            // eslint-disable-next-line
            db.redisSet = jest.fn(async (key, value, _, __) => {
                cache[key] = JSON.stringify(value as any)
            })

            // eslint-disable-next-line
            db.redisGet = jest.fn(async (key, defaultValue, options = {}) => {
                const { jsonSerialize = true } = options
                const value = cache[key]
                if (typeof value === 'undefined') {
                    return defaultValue
                }
                return value ? (jsonSerialize ? JSON.parse(value) : value) : null
            })
        })

        test('getPersonData returns the right data with and without cache', async () => {
            const distinctId = 'some_distinct_id'
            const team = await getFirstTeam(hub)

            await createPerson(hub, team, [distinctId], { foo: 'bar' })
            db.personInfoCachingEnabledTeams = new Set([2])

            const nonCachedPersonData = await db.getPersonData(team.id, distinctId)

            expect(nonCachedPersonData).not.toBeNull()

            const { uuid, createdAtIso, properties, team_id } = nonCachedPersonData as CachedPersonData

            expect(uuid).toEqual(expect.any(String))
            expect(createdAtIso).toEqual(expect.any(String))
            expect(properties).toEqual({ foo: 'bar' })
            expect(team_id).toEqual(team.id)

            expect((db.statsd?.increment as any).mock.calls.map((call: any[]) => call[0])).toContain(
                'person_info_cache.miss'
            )
            expect((db.statsd?.increment as any).mock.calls.map((call: any[]) => call[0])).not.toContain(
                'person_info_cache.hit'
            )

            const cachedPersonData = (await db.getPersonData(team.id, distinctId)) as CachedPersonData

            expect(cachedPersonData.uuid).toEqual(uuid)
            expect(cachedPersonData.createdAtIso).toEqual(createdAtIso)
            expect(cachedPersonData.properties).toEqual(properties)
            expect(cachedPersonData.team_id).toEqual(team_id)

            expect((db.statsd?.increment as any).mock.calls.map((call: any[]) => call[0])).toContain(
                'person_info_cache.hit'
            )
        })

        test('expect cache to be set when person is created', async () => {
            const distinctId = 'some_distinct_id'
            const team = await getFirstTeam(hub)

            // enable the cache before creating person
            db.personInfoCachingEnabledTeams = new Set([2])
            await createPerson(hub, team, [distinctId], { foo: 'bar' })

            const personData = (await db.getPersonData(team.id, distinctId)) as CachedPersonData

            expect(personData.properties).toEqual({ foo: 'bar' })

            // cache was hit
            expect((db.statsd?.increment as any).mock.calls.map((call: any[]) => call[0])).toContain(
                'person_info_cache.hit'
            )
        })
    })
})
