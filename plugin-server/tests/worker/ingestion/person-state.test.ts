import { PluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { Database, Hub, Person, RawPerson } from '../../../src/types'
import { DependencyUnavailableError } from '../../../src/utils/db/error'
import { createHub } from '../../../src/utils/db/hub'
import { UUIDT } from '../../../src/utils/utils'
import { LazyPersonContainer } from '../../../src/worker/ingestion/lazy-person-container'
import { ageInMonthsLowCardinality, PersonState } from '../../../src/worker/ingestion/person-state'
import { delayUntilEventIngested } from '../../helpers/clickhouse'
import { createOrganization, createTeam, insertRow } from '../../helpers/sql'

jest.setTimeout(5000) // 5 sec timeout

const timestamp = DateTime.fromISO('2020-01-01T12:00:05.200Z').toUTC()
const timestamp2 = DateTime.fromISO('2020-02-02T12:00:05.200Z').toUTC()
const timestampch = '2020-01-01 12:00:05.000'

describe.each([[true], [false]])('PersonState.update()', (poEEmbraceJoin) => {
    let hub: Hub
    let closeHub: () => Promise<void>

    let uuid: UUIDT
    let uuid2: UUIDT
    let teamId: number

    beforeAll(async () => {
        ;[hub, closeHub] = await createHub({})
        await hub.db.clickhouseQuery('SYSTEM STOP MERGES')
    })

    beforeEach(async () => {
        uuid = new UUIDT()
        uuid2 = new UUIDT()
        const organizationId = await createOrganization(hub.db.postgres)
        teamId = await createTeam(hub.db.postgres, organizationId)

        jest.spyOn(hub.personManager, 'isNewPerson')
        jest.spyOn(hub.db, 'fetchPerson')
        jest.spyOn(hub.db, 'updatePersonDeprecated')

        jest.useFakeTimers({ advanceTimers: 50 })
    })

    afterEach(() => {
        jest.clearAllTimers()
    })

    afterAll(async () => {
        await closeHub()
        await hub.db.clickhouseQuery('SYSTEM START MERGES')
    })

    function personState(event: Partial<PluginEvent>, person?: Person) {
        const fullEvent = {
            team_id: teamId,
            properties: {},
            ...event,
        }
        const personContainer = new LazyPersonContainer(teamId, event.distinct_id!, hub, person)
        return new PersonState(
            fullEvent as any,
            teamId,
            event.distinct_id!,
            timestamp,
            hub.db,
            hub.statsd,
            hub.personManager,
            personContainer,
            poEEmbraceJoin,
            uuid
        )
    }

    async function fetchPostgresPersons() {
        const query = `SELECT * FROM posthog_person WHERE team_id = ${teamId} ORDER BY id`
        return (await hub.db.postgresQuery(query, undefined, 'persons')).rows.map(
            // NOTE: we map to update some values here to maintain
            // compatibility with `hub.db.fetchPersons`.
            // TODO: remove unnecessary property translation operation.
            (rawPerson: RawPerson) =>
                ({
                    ...rawPerson,
                    created_at: DateTime.fromISO(rawPerson.created_at).toUTC(),
                    version: Number(rawPerson.version || 0),
                } as Person)
        )
    }

    async function fetchPersonsRows() {
        const query = `SELECT * FROM person FINAL WHERE team_id = ${teamId} ORDER BY _offset`
        return (await hub.db.clickhouseQuery(query)).data
    }

    async function fetchPersonsRowsWithVersionHigerEqualThan(version = 1) {
        const query = `SELECT * FROM person FINAL WHERE team_id = ${teamId} AND version >= ${version}`
        return (await hub.db.clickhouseQuery(query)).data
    }

    async function fetchDistinctIdsClickhouse(person: Person) {
        return hub.db.fetchDistinctIdValues(person, Database.ClickHouse)
    }

    async function fetchDistinctIdsClickhouseVersion1() {
        const query = `SELECT distinct_id FROM person_distinct_id2 FINAL WHERE team_id = ${teamId} AND version = 1`
        return (await hub.db.clickhouseQuery(query)).data
    }

    describe('on person creation', () => {
        it('creates person if they are new', async () => {
            const event_uuid = new UUIDT().toString()
            const personContainer = await personState({
                event: '$pageview',
                distinct_id: 'new-user',
                uuid: event_uuid,
            }).update()
            await hub.db.kafkaProducer.flush()

            expect(hub.personManager.isNewPerson).toHaveBeenCalledTimes(1)
            expect(hub.db.fetchPerson).toHaveBeenCalledTimes(0)
            expect(hub.db.updatePersonDeprecated).not.toHaveBeenCalled()

            // verify Postgres persons
            const persons = await fetchPostgresPersons()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid.toString(),
                    properties: { $creator_event_uuid: event_uuid },
                    created_at: timestamp,
                    version: 0,
                    is_identified: false,
                })
            )

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining(['new-user']))

            // verify personContainer
            expect(persons[0]).toEqual(await personContainer.get())
        })

        it('handles person being created in a race condition', async () => {
            const state = personState({ event: '$pageview', distinct_id: 'new-user' })
            await state.personContainer.get() // Pre-load person, with it returning undefined (e.g. as by buffer step)

            // Create person separately
            const racePersonContainer = await personState({ event: '$pageview', distinct_id: 'new-user' }).update()
            await hub.db.kafkaProducer.flush()
            const racePerson = await racePersonContainer.get()

            // Run person-state update. This will _not_ create the person as it was created in the last step, but should
            // still return the correct result
            const personContainer = await state.update()

            // verify Postgres persons
            const persons = await fetchPostgresPersons()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid.toString(),
                    properties: {},
                    created_at: timestamp,
                    version: 0,
                    is_identified: false,
                })
            )

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining(['new-user']))

            // verify personContainer
            expect(personContainer.loaded).toEqual(false)
            expect(persons[0]).toEqual(await personContainer.get())
            expect(await personContainer.get()).toEqual(racePerson)
        })

        it('handles person already being created by time `createPerson` is called', async () => {
            const state = personState({ event: '$pageview', distinct_id: 'new-user' })
            await state.personContainer.get() // Pre-load person, with it returning undefined (e.g. as by buffer step)

            // Create person separately
            const racePersonContainer = await personState({ event: '$pageview', distinct_id: 'new-user' }).update()
            await hub.db.kafkaProducer.flush()
            const racePerson = await racePersonContainer.get()

            jest.spyOn(hub.personManager, 'isNewPerson').mockResolvedValueOnce(true)

            // Run person-state update. This will try create the person, but fail and re-fetch it later.
            const personContainer = await state.update()

            // verify Postgres persons
            const persons = await fetchPostgresPersons()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid.toString(),
                    properties: {},
                    created_at: timestamp,
                    version: 0,
                    is_identified: false,
                })
            )

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining(['new-user']))

            // verify personContainer
            expect(personContainer.loaded).toEqual(false)
            expect(persons[0]).toEqual(await personContainer.get())
            expect(await personContainer.get()).toEqual(racePerson)
        })

        it('creates person with properties', async () => {
            const personContainer = await personState({
                event: '$pageview',
                distinct_id: 'new-user',
                properties: {
                    $set_once: { a: 1, b: 2 },
                    $set: { b: 3, c: 4 },
                },
            }).update()
            await hub.db.kafkaProducer.flush()

            expect(hub.personManager.isNewPerson).toHaveBeenCalledTimes(1)
            expect(hub.db.fetchPerson).toHaveBeenCalledTimes(0)
            expect(hub.db.updatePersonDeprecated).not.toHaveBeenCalled()

            // verify Postgres persons
            const persons = await fetchPostgresPersons()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid.toString(),
                    properties: { a: 1, b: 3, c: 4 },
                    created_at: timestamp,
                    version: 0,
                    is_identified: false,
                })
            )

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining(['new-user']))

            // verify personContainer
            expect(persons[0]).toEqual(await personContainer.get())
        })
    })

    describe('on person update', () => {
        it('updates person properties', async () => {
            await hub.db.createPerson(timestamp, { b: 3, c: 4 }, {}, {}, teamId, null, false, uuid.toString(), [
                'new-user',
            ])

            const personContainer = await personState({
                event: '$pageview',
                distinct_id: 'new-user',
                properties: {
                    $set_once: { c: 3, e: 4 },
                    $set: { b: 4 },
                },
            }).update()
            await hub.db.kafkaProducer.flush()

            expect(hub.personManager.isNewPerson).toHaveBeenCalledTimes(1)
            expect(hub.db.fetchPerson).toHaveBeenCalledTimes(1)

            // verify Postgres persons
            const persons = await fetchPostgresPersons()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid.toString(),
                    properties: { b: 4, c: 4, e: 4 },
                    created_at: timestamp,
                    version: 1,
                    is_identified: false,
                })
            )

            // verify personContainer
            expect(persons[0]).toEqual(await personContainer.get())
        })

        it('updating with cached person data skips checking if person is new', async () => {
            const person = await hub.db.createPerson(
                timestamp,
                { b: 3, c: 4 },
                {},
                {},
                teamId,
                null,
                false,
                uuid.toString(),
                ['new-user']
            )

            const personContainer = await personState(
                {
                    event: '$pageview',
                    distinct_id: 'new-user',
                    properties: {
                        $set_once: { c: 3, e: 4 },
                        $set: { b: 4 },
                    },
                },
                person
            ).update()
            await hub.db.kafkaProducer.flush()

            expect(hub.personManager.isNewPerson).toHaveBeenCalledTimes(0)
            expect(hub.db.fetchPerson).toHaveBeenCalledTimes(0)

            // verify Postgres persons
            const persons = await fetchPostgresPersons()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid.toString(),
                    properties: { b: 4, c: 4, e: 4 },
                    created_at: timestamp,
                    version: 1,
                    is_identified: false,
                })
            )

            // verify personContainer
            expect(persons[0]).toEqual(await personContainer.get())
        })

        it('does not update person if not needed', async () => {
            await hub.db.createPerson(timestamp, { b: 3, c: 4 }, {}, {}, teamId, null, false, uuid.toString(), [
                'new-user',
            ])

            const personContainer = await personState({
                event: '$pageview',
                distinct_id: 'new-user',
                properties: {
                    $set_once: { c: 3 },
                    $set: { b: 3 },
                },
            }).update()
            await hub.db.kafkaProducer.flush()

            expect(hub.db.fetchPerson).toHaveBeenCalledTimes(1)
            expect(hub.db.updatePersonDeprecated).not.toHaveBeenCalled()

            // verify Postgres persons
            const persons = await fetchPostgresPersons()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid.toString(),
                    properties: { b: 3, c: 4 },
                    created_at: timestamp,
                    version: 0,
                    is_identified: false,
                })
            )

            // verify personContainer
            expect(persons[0]).toEqual(await personContainer.get())
        })
    })

    describe('on $identify event', () => {
        it('creates person and sets is_identified false when $anon_distinct_id not passed', async () => {
            const personContainer = await personState({
                event: '$identify',
                distinct_id: 'new-user',
                properties: {
                    $set: { foo: 'bar' },
                },
            }).update()
            await hub.db.kafkaProducer.flush()

            expect(hub.db.updatePersonDeprecated).not.toHaveBeenCalled()

            // verify Postgres persons
            const persons = await fetchPostgresPersons()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid.toString(),
                    properties: { foo: 'bar' },
                    created_at: timestamp,
                    version: 0,
                    is_identified: false,
                })
            )

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining(['new-user']))

            // verify personContainer
            expect(persons[0]).toEqual(await personContainer.get())
        })

        it('creates person with both distinct_ids and marks user as is_identified when $anon_distinct_id passed', async () => {
            const personContainer = await personState({
                event: '$identify',
                distinct_id: 'new-user',
                properties: {
                    $set: { foo: 'bar' },
                    $anon_distinct_id: 'old-user',
                },
            }).update()
            await hub.db.kafkaProducer.flush()

            expect(hub.db.updatePersonDeprecated).not.toHaveBeenCalled()

            // verify Postgres persons
            const persons = await fetchPostgresPersons()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid.toString(),
                    properties: { foo: 'bar' },
                    created_at: timestamp,
                    version: 0,
                    is_identified: true,
                })
            )

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))

            // verify personContainer
            expect(persons[0]).toEqual(await personContainer.get())
        })

        it('updates person properties leaves is_identified false when no anon_distinct_id passed', async () => {
            await hub.db.createPerson(timestamp, { b: 3, c: 4 }, {}, {}, teamId, null, false, uuid.toString(), [
                'new-user',
            ])

            const personContainer = await personState({
                event: '$identify',
                distinct_id: 'new-user',
                properties: {
                    $set_once: { c: 3, e: 4 },
                    $set: { b: 4 },
                },
            }).update()
            await hub.db.kafkaProducer.flush()

            expect(hub.personManager.isNewPerson).toHaveBeenCalledTimes(1)
            expect(hub.db.fetchPerson).toHaveBeenCalledTimes(1)
            expect(hub.db.updatePersonDeprecated).toHaveBeenCalledTimes(1)

            // verify Postgres persons
            const persons = await fetchPostgresPersons()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid.toString(),
                    properties: { b: 4, c: 4, e: 4 },
                    created_at: timestamp,
                    version: 1,
                    is_identified: false,
                })
            )

            // verify personContainer
            expect(persons[0]).toEqual(await personContainer.get())
        })

        it('marks user as is_identified when no changes to distinct_ids but $anon_distinct_id passed', async () => {
            await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, uuid.toString(), [
                'new-user',
                'old-user',
            ])

            await personState({
                event: '$identify',
                distinct_id: 'new-user',
                properties: {
                    $anon_distinct_id: 'old-user',
                },
            }).update()
            await hub.db.kafkaProducer.flush()

            expect(hub.db.updatePersonDeprecated).toHaveBeenCalledTimes(1)

            // verify Postgres persons
            const persons = await fetchPostgresPersons()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    uuid: uuid.toString(),
                    version: 1,
                    is_identified: true,
                })
            )
        })

        it('does not update person if already is_identified and no properties changes', async () => {
            await hub.db.createPerson(timestamp, { b: 3, c: 4 }, {}, {}, teamId, null, true, uuid.toString(), [
                'new-user',
                'old-user',
            ])

            const personContainer = await personState({
                event: '$identify',
                distinct_id: 'new-user',
                properties: {
                    $anon_distinct_id: 'old-user',
                    $set_once: { c: 3 },
                    $set: { b: 3 },
                },
            }).update()
            await hub.db.kafkaProducer.flush()

            expect(hub.db.updatePersonDeprecated).not.toHaveBeenCalled()

            // verify Postgres persons
            const persons = await fetchPostgresPersons()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid.toString(),
                    properties: { b: 3, c: 4 },
                    created_at: timestamp,
                    version: 0,
                    is_identified: true,
                })
            )

            // verify personContainer
            expect(persons[0]).toEqual(await personContainer.get())
        })

        it('add distinct id and marks user is_identified when passed $anon_distinct_id person does not exists and distinct_id does', async () => {
            await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, uuid.toString(), ['new-user'])

            const personContainer = await personState({
                event: '$identify',
                distinct_id: 'new-user',
                properties: {
                    $anon_distinct_id: 'old-user',
                },
            }).update()
            await hub.db.kafkaProducer.flush()

            // verify Postgres persons
            const persons = await fetchPostgresPersons()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid.toString(),
                    properties: {},
                    created_at: timestamp,
                    version: 1,
                    is_identified: true,
                })
            )

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))

            // verify personContainer
            expect(persons[0]).toEqual(await personContainer.get())
        })

        it('add distinct id and marks user as is_identified when passed $anon_distinct_id person exists and distinct_id does not', async () => {
            await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, uuid.toString(), ['old-user'])

            const personContainer = await personState({
                event: '$identify',
                distinct_id: 'new-user',
                properties: {
                    $anon_distinct_id: 'old-user',
                },
            }).update()
            await hub.db.kafkaProducer.flush()

            // verify Postgres persons
            const persons = await fetchPostgresPersons()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid.toString(),
                    properties: {},
                    created_at: timestamp,
                    version: 1,
                    is_identified: true,
                })
            )

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))

            // verify personContainer
            expect(persons[0]).toEqual(await personContainer.get())
        })

        it('add distinct id, marks user as is_identified and updates properties when one of the persons exists and properties are passed', async () => {
            await hub.db.createPerson(timestamp, { b: 3, c: 4 }, {}, {}, teamId, null, false, uuid.toString(), [
                'new-user',
            ])

            const personContainer = await personState({
                event: '$identify',
                distinct_id: 'new-user',
                properties: {
                    $anon_distinct_id: 'old-user',
                    $set_once: { c: 3, e: 4 },
                    $set: { b: 4 },
                },
            }).update()
            await hub.db.kafkaProducer.flush()

            // verify Postgres persons
            const persons = await fetchPostgresPersons()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid.toString(),
                    properties: { b: 4, c: 4, e: 4 },
                    created_at: timestamp,
                    version: 1,
                    is_identified: true,
                })
            )

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))

            // verify personContainer
            expect(persons[0]).toEqual(await personContainer.get())
        })

        it('merge into distinct_id person and marks user as is_identified when both persons have is_identified false', async () => {
            await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, uuid.toString(), ['old-user'])
            await hub.db.createPerson(timestamp2, {}, {}, {}, teamId, null, false, uuid2.toString(), ['new-user'])

            const personContainer = await personState({
                event: '$identify',
                distinct_id: 'new-user',
                properties: {
                    $anon_distinct_id: 'old-user',
                },
            }).update()
            await hub.db.kafkaProducer.flush()

            // verify Postgres persons
            const persons = await fetchPostgresPersons()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: expect.any(String),
                    properties: {},
                    created_at: timestamp,
                    version: 1,
                    is_identified: true,
                })
            )
            expect([uuid.toString(), uuid2.toString()]).toContain(persons[0].uuid)

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))

            // verify ClickHouse persons
            await delayUntilEventIngested(() => fetchPersonsRowsWithVersionHigerEqualThan(), 2) // wait until merge and delete processed
            const clickhousePersons = await fetchPersonsRows() // but verify full state
            expect(clickhousePersons.length).toEqual(2)
            expect(clickhousePersons).toEqual(
                expect.arrayContaining([
                    expect.objectContaining({
                        id: expect.any(String),
                        properties: '{}',
                        created_at: timestampch,
                        version: 1,
                        is_identified: 1,
                    }),
                    expect.objectContaining({
                        id: expect.any(String),
                        is_deleted: 1,
                        version: 100,
                    }),
                ])
            )
            expect(new Set(clickhousePersons.map((p) => p.id))).toEqual(new Set([uuid.toString(), uuid2.toString()]))

            // verify ClickHouse distinct_ids
            await delayUntilEventIngested(() => fetchDistinctIdsClickhouseVersion1())
            const clickHouseDistinctIds = await fetchDistinctIdsClickhouse(persons[0])
            expect(clickHouseDistinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))

            // verify personContainer
            expect(persons[0]).toEqual(await personContainer.get())
        })

        it('merge into distinct_id person and marks user as is_identified when distinct_id user is identified and $anon_distinct_id user is not', async () => {
            await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, uuid.toString(), ['old-user'])
            await hub.db.createPerson(timestamp2, {}, {}, {}, teamId, null, true, uuid2.toString(), ['new-user'])

            const personContainer = await personState({
                event: '$identify',
                distinct_id: 'new-user',
                properties: {
                    $anon_distinct_id: 'old-user',
                },
            }).update()
            await hub.db.kafkaProducer.flush()

            // verify Postgres persons
            const persons = await fetchPostgresPersons()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: expect.any(String),
                    properties: {},
                    created_at: timestamp,
                    version: 1,
                    is_identified: true,
                })
            )
            expect([uuid.toString(), uuid2.toString()]).toContain(persons[0].uuid)

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))

            // verify ClickHouse persons
            await delayUntilEventIngested(() => fetchPersonsRowsWithVersionHigerEqualThan(), 2) // wait until merge and delete processed
            const clickhousePersons = await fetchPersonsRows() // but verify full state
            expect(clickhousePersons.length).toEqual(2)
            expect(clickhousePersons).toEqual(
                expect.arrayContaining([
                    expect.objectContaining({
                        id: expect.any(String),
                        properties: '{}',
                        created_at: timestampch,
                        version: 1,
                        is_identified: 1,
                    }),
                    expect.objectContaining({
                        id: expect.any(String),
                        is_deleted: 1,
                        version: 100,
                    }),
                ])
            )
            expect(new Set(clickhousePersons.map((p) => p.id))).toEqual(new Set([uuid.toString(), uuid2.toString()]))

            // verify ClickHouse distinct_ids
            await delayUntilEventIngested(() => fetchDistinctIdsClickhouseVersion1())
            const clickHouseDistinctIds = await fetchDistinctIdsClickhouse(persons[0])
            expect(clickHouseDistinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))

            // verify personContainer
            expect(persons[0]).toEqual(await personContainer.get())
        })

        it('does not merge people when distinct_id user is not identified and $anon_distinct_id user is', async () => {
            await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, true, uuid.toString(), ['old-user'])
            await hub.db.createPerson(timestamp2, {}, {}, {}, teamId, null, false, uuid2.toString(), ['new-user'])

            const personContainer = await personState({
                event: '$identify',
                distinct_id: 'new-user',
                properties: {
                    $anon_distinct_id: 'old-user',
                },
            }).update()
            await hub.db.kafkaProducer.flush()

            // verify Postgres persons
            const persons = (await fetchPostgresPersons()).sort((a, b) => a.id - b.id)
            expect(persons.length).toEqual(2)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid.toString(),
                    properties: {},
                    created_at: timestamp,
                    version: 0,
                    is_identified: true,
                })
            )
            expect(persons[1]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid2.toString(),
                    properties: {},
                    created_at: timestamp2,
                    version: 1,
                    is_identified: true,
                })
            )

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining(['old-user']))
            const distinctIds2 = await hub.db.fetchDistinctIdValues(persons[1])
            expect(distinctIds2).toEqual(expect.arrayContaining(['new-user']))

            // verify personContainer
            expect(persons[1]).toEqual(await personContainer.get())
        })

        it('does not merge people when both users are identified', async () => {
            await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, true, uuid.toString(), ['old-user'])
            await hub.db.createPerson(timestamp2, {}, {}, {}, teamId, null, true, uuid2.toString(), ['new-user'])

            const personContainer = await personState({
                event: '$identify',
                distinct_id: 'new-user',
                properties: {
                    $anon_distinct_id: 'old-user',
                },
            }).update()
            await hub.db.kafkaProducer.flush()

            // verify Postgres persons
            const persons = (await fetchPostgresPersons()).sort((a, b) => a.id - b.id)
            expect(persons.length).toEqual(2)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid.toString(),
                    properties: {},
                    created_at: timestamp,
                    version: 0,
                    is_identified: true,
                })
            )
            expect(persons[1]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid2.toString(),
                    properties: {},
                    created_at: timestamp2,
                    version: 0,
                    is_identified: true,
                })
            )

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining(['old-user']))
            const distinctIds2 = await hub.db.fetchDistinctIdValues(persons[1])
            expect(distinctIds2).toEqual(expect.arrayContaining(['new-user']))

            // verify personContainer
            expect(persons[1]).toEqual(await personContainer.get())
        })

        it('merge into distinct_id person and updates properties with $set/$set_once', async () => {
            await hub.db.createPerson(timestamp, { a: 1, b: 2 }, {}, {}, teamId, null, false, uuid.toString(), [
                'old-user',
            ])
            await hub.db.createPerson(timestamp2, { b: 3, c: 4, d: 5 }, {}, {}, teamId, null, false, uuid2.toString(), [
                'new-user',
            ])

            const personContainer = await personState({
                event: '$identify',
                distinct_id: 'new-user',
                properties: {
                    $set: { d: 6, e: 7 },
                    $set_once: { a: 8, f: 9 },
                    $anon_distinct_id: 'old-user',
                },
            }).update()
            await hub.db.kafkaProducer.flush()

            // verify Postgres persons
            const persons = await fetchPostgresPersons()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: expect.any(String),
                    properties: { a: 1, b: 3, c: 4, d: 6, e: 7, f: 9 },
                    created_at: timestamp,
                    version: 1,
                    is_identified: true,
                })
            )
            expect([uuid.toString(), uuid2.toString()]).toContain(persons[0].uuid)

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))

            // verify ClickHouse persons
            await delayUntilEventIngested(() => fetchPersonsRowsWithVersionHigerEqualThan(), 2) // wait until merge and delete processed
            const clickhousePersons = await fetchPersonsRows() // but verify full state
            expect(clickhousePersons.length).toEqual(2)
            expect(clickhousePersons).toEqual(
                expect.arrayContaining([
                    expect.objectContaining({
                        id: expect.any(String),
                        properties: JSON.stringify({ a: 1, b: 3, c: 4, d: 6, e: 7, f: 9 }),
                        created_at: timestampch,
                        version: 1,
                        is_identified: 1,
                    }),
                    expect.objectContaining({
                        id: expect.any(String),
                        is_deleted: 1,
                        version: 100,
                    }),
                ])
            )
            expect(new Set(clickhousePersons.map((p) => p.id))).toEqual(new Set([uuid.toString(), uuid2.toString()]))

            // verify ClickHouse distinct_ids
            await delayUntilEventIngested(() => fetchDistinctIdsClickhouseVersion1())
            const clickHouseDistinctIds = await fetchDistinctIdsClickhouse(persons[0])
            expect(clickHouseDistinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))

            // verify personContainer
            expect(persons[0]).toEqual(await personContainer.get())
        })

        it('updates person properties when other thread merges the user', async () => {
            const cachedPerson = await hub.db.createPerson(
                timestamp,
                { a: 1, b: 2 },
                {},
                {},
                teamId,
                null,
                false,
                uuid.toString(),
                ['old-user']
            )
            await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, uuid2.toString(), ['new-user'])
            const mergedPersonContainer = await personState({
                event: '$identify',
                distinct_id: 'new-user',
                properties: {
                    $anon_distinct_id: 'old-user',
                },
            }).update()
            const mergedPerson = await mergedPersonContainer.get()
            // Prerequisite for the test - UUID changes
            expect(mergedPerson!.uuid).not.toEqual(cachedPerson.uuid)

            jest.mocked(hub.db.fetchPerson).mockClear() // Reset counter

            const personContainer = await personState(
                {
                    event: '$pageview',
                    distinct_id: 'new-user',
                    properties: {
                        $set_once: { c: 3, e: 4 },
                        $set: { b: 4 },
                    },
                },
                cachedPerson
            ).update()

            await hub.db.kafkaProducer.flush()

            expect(hub.db.fetchPerson).toHaveBeenCalledTimes(1) // It does a single reset after failing once
            expect(hub.personManager.isNewPerson).toHaveBeenCalledTimes(0)

            // verify Postgres persons
            const persons = await fetchPostgresPersons()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid2.toString(),
                    properties: { a: 1, b: 4, c: 3, e: 4 },
                    created_at: timestamp,
                    version: 2,
                    is_identified: true,
                })
            )

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))

            // verify ClickHouse persons
            await delayUntilEventIngested(() => fetchPersonsRowsWithVersionHigerEqualThan(2), 2) // wait until merge and delete processed
            const clickhousePersons = await fetchPersonsRows() // but verify full state
            expect(clickhousePersons.length).toEqual(2)
            expect(clickhousePersons).toEqual(
                expect.arrayContaining([
                    expect.objectContaining({
                        id: uuid2.toString(),
                        properties: JSON.stringify({ a: 1, b: 4, c: 3, e: 4 }),
                        is_deleted: 0,
                        is_identified: 1,
                        created_at: timestampch,
                        version: 2,
                    }),
                    expect.objectContaining({
                        id: uuid.toString(),
                        is_deleted: 1,
                        version: 100,
                    }),
                ])
            )

            // verify ClickHouse distinct_ids
            await delayUntilEventIngested(() => fetchDistinctIdsClickhouseVersion1())
            const clickHouseDistinctIds = await fetchDistinctIdsClickhouse(persons[0])
            expect(clickHouseDistinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))

            // verify personContainer
            expect(persons[0]).toEqual(await personContainer.get())
        })
    })

    describe('on $create_alias event', () => {
        it('creates person and sets is_identified false when alias property not passed', async () => {
            const personContainer = await personState({
                event: '$create_alias',
                distinct_id: 'new-user',
                properties: {
                    $set: { foo: 'bar' },
                },
            }).update()
            await hub.db.kafkaProducer.flush()

            expect(hub.db.updatePersonDeprecated).not.toHaveBeenCalled()

            // verify Postgres persons
            const persons = await fetchPostgresPersons()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid.toString(),
                    properties: { foo: 'bar' },
                    created_at: timestamp,
                    version: 0,
                    is_identified: false,
                })
            )

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining(['new-user']))

            // verify personContainer
            expect(persons[0]).toEqual(await personContainer.get())
        })

        it('creates person with both distinct_ids and marks user as is_identified when alias property passed', async () => {
            const personContainer = await personState({
                event: '$create_alias',
                distinct_id: 'new-user',
                properties: {
                    $set: { foo: 'bar' },
                    alias: 'old-user',
                },
            }).update()
            await hub.db.kafkaProducer.flush()

            expect(hub.db.updatePersonDeprecated).not.toHaveBeenCalled()

            // verify Postgres persons
            const persons = await fetchPostgresPersons()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid.toString(),
                    properties: { foo: 'bar' },
                    created_at: timestamp,
                    version: 0,
                    is_identified: true,
                })
            )

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))

            // verify personContainer
            expect(persons[0]).toEqual(await personContainer.get())
        })

        it('updates person properties leaves is_identified false when no alias property passed', async () => {
            await hub.db.createPerson(timestamp, { b: 3, c: 4 }, {}, {}, teamId, null, false, uuid.toString(), [
                'new-user',
            ])

            const personContainer = await personState({
                event: '$create_alias',
                distinct_id: 'new-user',
                properties: {
                    $set_once: { c: 3, e: 4 },
                    $set: { b: 4 },
                },
            }).update()
            await hub.db.kafkaProducer.flush()

            expect(hub.personManager.isNewPerson).toHaveBeenCalledTimes(1)
            expect(hub.db.fetchPerson).toHaveBeenCalledTimes(1)
            expect(hub.db.updatePersonDeprecated).toHaveBeenCalledTimes(1)

            // verify Postgres persons
            const persons = await fetchPostgresPersons()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid.toString(),
                    properties: { b: 4, c: 4, e: 4 },
                    created_at: timestamp,
                    version: 1,
                    is_identified: false,
                })
            )

            // verify personContainer
            expect(persons[0]).toEqual(await personContainer.get())
        })

        it('marks user as is_identified when no changes to distinct_ids but alias property passed', async () => {
            await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, uuid.toString(), [
                'new-user',
                'old-user',
            ])

            await personState({
                event: '$create_alias',
                distinct_id: 'new-user',
                properties: {
                    alias: 'old-user',
                },
            }).update()
            await hub.db.kafkaProducer.flush()

            expect(hub.db.updatePersonDeprecated).toHaveBeenCalledTimes(1)

            // verify Postgres persons
            const persons = await fetchPostgresPersons()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    uuid: uuid.toString(),
                    version: 1,
                    is_identified: true,
                })
            )
        })
        it('add distinct id and marks user is_identified when passed alias property whos person does not exists and distinct_id does', async () => {
            await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, uuid.toString(), ['new-user'])

            const personContainer = await personState({
                event: '$create_alias',
                distinct_id: 'new-user',
                properties: {
                    alias: 'old-user',
                },
            }).update()
            await hub.db.kafkaProducer.flush()

            // verify Postgres persons
            const persons = await fetchPostgresPersons()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid.toString(),
                    properties: {},
                    created_at: timestamp,
                    version: 1,
                    is_identified: true,
                })
            )

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))

            // verify personContainer
            expect(persons[0]).toEqual(await personContainer.get())
        })

        it('add distinct id and marks user as is_identified when passed alias property id whos person exists and distinct_id does not', async () => {
            await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, uuid.toString(), ['old-user'])

            const personContainer = await personState({
                event: '$create_alias',
                distinct_id: 'new-user',
                properties: {
                    alias: 'old-user',
                },
            }).update()
            await hub.db.kafkaProducer.flush()

            // verify Postgres persons
            const persons = await fetchPostgresPersons()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid.toString(),
                    properties: {},
                    created_at: timestamp,
                    version: 1,
                    is_identified: true,
                })
            )

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))

            // verify personContainer
            expect(persons[0]).toEqual(await personContainer.get())
        })

        it('add distinct id, marks user as is_identified and updates properties when one of the persons exists and properties are passed', async () => {
            await hub.db.createPerson(timestamp, { b: 3, c: 4 }, {}, {}, teamId, null, false, uuid.toString(), [
                'new-user',
            ])

            const personContainer = await personState({
                event: '$create_alias',
                distinct_id: 'new-user',
                properties: {
                    alias: 'old-user',
                    $set_once: { c: 3, e: 4 },
                    $set: { b: 4 },
                },
            }).update()
            await hub.db.kafkaProducer.flush()

            // verify Postgres persons
            const persons = await fetchPostgresPersons()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid.toString(),
                    properties: { b: 4, c: 4, e: 4 },
                    created_at: timestamp,
                    version: 1,
                    is_identified: true,
                })
            )

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))

            // verify personContainer
            expect(persons[0]).toEqual(await personContainer.get())
        })

        it('does not merge people when alias id user is identified', async () => {
            await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, true, uuid.toString(), ['old-user'])
            await hub.db.createPerson(timestamp2, {}, {}, {}, teamId, null, false, uuid2.toString(), ['new-user'])

            const personContainer = await personState({
                event: '$create_alias',
                distinct_id: 'new-user',
                properties: {
                    alias: 'old-user',
                },
            }).update()
            await hub.db.kafkaProducer.flush()

            // verify Postgres persons
            const persons = (await fetchPostgresPersons()).sort((a, b) => a.id - b.id)
            expect(persons.length).toEqual(2)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid.toString(),
                    properties: {},
                    created_at: timestamp,
                    version: 0,
                    is_identified: true,
                })
            )
            expect(persons[1]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid2.toString(),
                    properties: {},
                    created_at: timestamp2,
                    version: 1,
                    is_identified: true,
                })
            )

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining(['old-user']))
            const distinctIds2 = await hub.db.fetchDistinctIdValues(persons[1])
            expect(distinctIds2).toEqual(expect.arrayContaining(['new-user']))

            // verify personContainer
            expect(persons[1]).toEqual(await personContainer.get())
        })

        it('merge into distinct_id person and marks user as is_identified when both persons have is_identified false', async () => {
            await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, uuid.toString(), ['old-user'])
            await hub.db.createPerson(timestamp2, {}, {}, {}, teamId, null, false, uuid2.toString(), ['new-user'])

            const personContainer = await personState({
                event: '$create_alias',
                distinct_id: 'new-user',
                properties: {
                    alias: 'old-user',
                },
            }).update()
            await hub.db.kafkaProducer.flush()

            // verify Postgres persons
            const persons = await fetchPostgresPersons()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: expect.any(String),
                    properties: {},
                    created_at: timestamp,
                    version: 1,
                    is_identified: true,
                })
            )
            expect([uuid.toString(), uuid2.toString()]).toContain(persons[0].uuid)

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))

            // verify ClickHouse persons
            await delayUntilEventIngested(() => fetchPersonsRowsWithVersionHigerEqualThan(), 2) // wait until merge and delete processed
            const clickhousePersons = await fetchPersonsRows() // but verify full state
            expect(clickhousePersons.length).toEqual(2)
            expect(clickhousePersons).toEqual(
                expect.arrayContaining([
                    expect.objectContaining({
                        id: expect.any(String),
                        properties: '{}',
                        created_at: timestampch,
                        version: 1,
                        is_identified: 1,
                    }),
                    expect.objectContaining({
                        id: expect.any(String),
                        is_deleted: 1,
                        version: 100,
                    }),
                ])
            )
            expect(new Set(clickhousePersons.map((p) => p.id))).toEqual(new Set([uuid.toString(), uuid2.toString()]))

            // verify ClickHouse distinct_ids
            await delayUntilEventIngested(() => fetchDistinctIdsClickhouseVersion1())
            const clickHouseDistinctIds = await fetchDistinctIdsClickhouse(persons[0])
            expect(clickHouseDistinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))

            // verify personContainer
            expect(persons[0]).toEqual(await personContainer.get())
        })

        it('merge into distinct_id person and marks user as is_identified when distinct_id user is identified and alias property id user is not', async () => {
            await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, uuid.toString(), ['old-user'])
            await hub.db.createPerson(timestamp2, {}, {}, {}, teamId, null, true, uuid2.toString(), ['new-user'])

            const personContainer = await personState({
                event: '$create_alias',
                distinct_id: 'new-user',
                properties: {
                    alias: 'old-user',
                },
            }).update()
            await hub.db.kafkaProducer.flush()

            // verify Postgres persons
            const persons = await fetchPostgresPersons()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: expect.any(String),
                    properties: {},
                    created_at: timestamp,
                    version: 1,
                    is_identified: true,
                })
            )
            expect([uuid.toString(), uuid2.toString()]).toContain(persons[0].uuid)

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))

            // verify ClickHouse persons
            await delayUntilEventIngested(() => fetchPersonsRowsWithVersionHigerEqualThan(), 2) // wait until merge and delete processed
            const clickhousePersons = await fetchPersonsRows() // but verify full state
            expect(clickhousePersons.length).toEqual(2)
            expect(clickhousePersons).toEqual(
                expect.arrayContaining([
                    expect.objectContaining({
                        id: expect.any(String),
                        properties: '{}',
                        created_at: timestampch,
                        version: 1,
                        is_identified: 1,
                    }),
                    expect.objectContaining({
                        id: expect.any(String),
                        is_deleted: 1,
                        version: 100,
                    }),
                ])
            )
            expect(new Set(clickhousePersons.map((p) => p.id))).toEqual(new Set([uuid.toString(), uuid2.toString()]))

            // verify ClickHouse distinct_ids
            await delayUntilEventIngested(() => fetchDistinctIdsClickhouseVersion1())
            const clickHouseDistinctIds = await fetchDistinctIdsClickhouse(persons[0])
            expect(clickHouseDistinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))

            // verify personContainer
            expect(persons[0]).toEqual(await personContainer.get())
        })

        it('merge into distinct_id person and updates properties with $set/$set_once', async () => {
            await hub.db.createPerson(timestamp, { a: 1, b: 2 }, {}, {}, teamId, null, false, uuid.toString(), [
                'old-user',
            ])
            await hub.db.createPerson(timestamp2, { b: 3, c: 4, d: 5 }, {}, {}, teamId, null, false, uuid2.toString(), [
                'new-user',
            ])

            const personContainer = await personState({
                event: '$create_alias',
                distinct_id: 'new-user',
                properties: {
                    $set: { d: 6, e: 7 },
                    $set_once: { a: 8, f: 9 },
                    alias: 'old-user',
                },
            }).update()
            await hub.db.kafkaProducer.flush()

            // verify Postgres persons
            const persons = await fetchPostgresPersons()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: expect.any(String),
                    properties: { a: 1, b: 3, c: 4, d: 6, e: 7, f: 9 },
                    created_at: timestamp,
                    version: 1,
                    is_identified: true,
                })
            )
            expect([uuid.toString(), uuid2.toString()]).toContain(persons[0].uuid)

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))

            // verify ClickHouse persons
            await delayUntilEventIngested(() => fetchPersonsRowsWithVersionHigerEqualThan(), 2) // wait until merge and delete processed
            const clickhousePersons = await fetchPersonsRows() // but verify full state
            expect(clickhousePersons.length).toEqual(2)
            expect(clickhousePersons).toEqual(
                expect.arrayContaining([
                    expect.objectContaining({
                        id: expect.any(String),
                        properties: JSON.stringify({ a: 1, b: 3, c: 4, d: 6, e: 7, f: 9 }),
                        created_at: timestampch,
                        version: 1,
                        is_identified: 1,
                    }),
                    expect.objectContaining({
                        id: expect.any(String),
                        is_deleted: 1,
                        version: 100,
                    }),
                ])
            )
            expect(new Set(clickhousePersons.map((p) => p.id))).toEqual(new Set([uuid.toString(), uuid2.toString()]))

            // verify ClickHouse distinct_ids
            await delayUntilEventIngested(() => fetchDistinctIdsClickhouseVersion1())
            const clickHouseDistinctIds = await fetchDistinctIdsClickhouse(persons[0])
            expect(clickHouseDistinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))

            // verify personContainer
            expect(persons[0]).toEqual(await personContainer.get())
        })
    })

    describe('illegal aliasing', () => {
        beforeEach(() => {
            hub.statsd = { increment: jest.fn() } as any
        })

        it('stops $identify if current distinct_id is illegal', async () => {
            await personState({
                event: '$identify',
                distinct_id: '[object Object]',
                properties: {
                    $anon_distinct_id: 'anonymous_id',
                },
            }).update()

            const persons = await fetchPostgresPersons()
            expect(persons.length).toEqual(1)

            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining(['[object Object]']))
            expect(hub.statsd!.increment).toHaveBeenCalledWith('illegal_distinct_ids.total', {
                distinctId: '[object Object]',
            })
        })

        it('stops $identify if $anon_distinct_id is illegal', async () => {
            await personState({
                event: '$identify',
                distinct_id: 'some_distinct_id',
                properties: {
                    $anon_distinct_id: 'undefined',
                },
            }).update()

            const persons = await fetchPostgresPersons()
            expect(persons.length).toEqual(1)

            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining(['some_distinct_id']))
            expect(hub.statsd!.increment).toHaveBeenCalledWith('illegal_distinct_ids.total', {
                distinctId: 'undefined',
            })
        })

        it('stops $create_alias if current distinct_id is illegal', async () => {
            await personState({
                event: '$create_alias',
                distinct_id: 'false',
                properties: {
                    alias: 'some_distinct_id',
                },
            }).update()

            const persons = await fetchPostgresPersons()
            expect(persons.length).toEqual(1)

            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining(['false']))
            expect(hub.statsd!.increment).toHaveBeenCalledWith('illegal_distinct_ids.total', {
                distinctId: 'false',
            })
        })

        it('stops $create_alias if alias is illegal', async () => {
            await personState({
                event: '$create_alias',
                distinct_id: 'some_distinct_id',
                properties: {
                    alias: 'null',
                },
            }).update()

            const persons = await fetchPostgresPersons()
            expect(persons.length).toEqual(1)

            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining(['some_distinct_id']))
            expect(hub.statsd!.increment).toHaveBeenCalledWith('illegal_distinct_ids.total', { distinctId: 'null' })
        })
    })

    describe('foreign key updates in other tables', () => {
        it('handles feature flag hash key overrides with no conflicts', async () => {
            const anonPerson = await hub.db.createPerson(
                timestamp.minus({ hours: 1 }),
                {},
                {},
                {},
                teamId,
                null,
                false,
                uuid.toString(),
                ['anonymous_id']
            )
            const identifiedPerson = await hub.db.createPerson(
                timestamp,
                {},
                {},
                {},
                teamId,
                null,
                false,
                uuid2.toString(),
                ['new_distinct_id']
            )

            // existing overrides
            await insertRow(hub.db.postgres, 'posthog_featureflaghashkeyoverride', {
                team_id: teamId,
                person_id: anonPerson.id,
                feature_flag_key: 'beta-feature',
                hash_key: 'example_id',
            })
            await insertRow(hub.db.postgres, 'posthog_featureflaghashkeyoverride', {
                team_id: teamId,
                person_id: identifiedPerson.id,
                feature_flag_key: 'multivariate-flag',
                hash_key: 'example_id',
            })

            // this event means the person will be merged
            // so hashkeyoverride should be updated to the new person id whichever way we merged
            await personState({
                event: '$identify',
                distinct_id: 'new_distinct_id',
                properties: {
                    $anon_distinct_id: 'anonymous_id',
                    distinct_id: 'new_distinct_id',
                },
            }).update()
            await hub.db.kafkaProducer.flush()

            const [person] = await fetchPostgresPersons()
            expect([identifiedPerson.id, anonPerson.id]).toContain(person.id)
            expect(await hub.db.fetchDistinctIdValues(person)).toEqual(['anonymous_id', 'new_distinct_id'])
            expect(person.is_identified).toEqual(true)

            const result = await hub.db.postgresQuery(
                `SELECT "feature_flag_key", "person_id", "hash_key" FROM "posthog_featureflaghashkeyoverride" WHERE "team_id" = $1`,
                [teamId],
                'testQueryHashKeyOverride'
            )
            expect(result.rows).toEqual(
                expect.arrayContaining([
                    {
                        feature_flag_key: 'beta-feature',
                        person_id: person.id,
                        hash_key: 'example_id',
                    },
                    {
                        feature_flag_key: 'multivariate-flag',
                        person_id: person.id,
                        hash_key: 'example_id',
                    },
                ])
            )
        })

        it('handles feature flag hash key overrides with some conflicts handled gracefully', async () => {
            const anonPerson = await hub.db.createPerson(
                timestamp.minus({ hours: 1 }),
                {},
                {},
                {},
                teamId,
                null,
                false,
                uuid.toString(),
                ['anonymous_id']
            )
            const identifiedPerson = await hub.db.createPerson(
                timestamp,
                {},
                {},
                {},
                teamId,
                null,
                false,
                uuid2.toString(),
                ['new_distinct_id']
            )

            // existing overrides for both anonPerson and identifiedPerson
            // which implies a clash when they are merged
            await insertRow(hub.db.postgres, 'posthog_featureflaghashkeyoverride', {
                team_id: teamId,
                person_id: anonPerson.id,
                feature_flag_key: 'beta-feature',
                hash_key: 'anon_id',
            })
            await insertRow(hub.db.postgres, 'posthog_featureflaghashkeyoverride', {
                team_id: teamId,
                person_id: identifiedPerson.id,
                feature_flag_key: 'beta-feature',
                hash_key: 'identified_id',
            })
            await insertRow(hub.db.postgres, 'posthog_featureflaghashkeyoverride', {
                team_id: teamId,
                person_id: anonPerson.id,
                feature_flag_key: 'multivariate-flag',
                hash_key: 'other_different_id',
            })

            // this event means the person will be merged
            // so hashkeyoverride should be updated to be either
            // we're optimizing on updates to not write on conflict and ordering is not guaranteed
            await personState({
                event: '$identify',
                distinct_id: 'new_distinct_id',
                properties: {
                    $anon_distinct_id: 'anonymous_id',
                    distinct_id: 'new_distinct_id',
                },
            }).update()
            await hub.db.kafkaProducer.flush()

            const [person] = await fetchPostgresPersons()
            expect([identifiedPerson.id, anonPerson.id]).toContain(person.id)
            expect(await hub.db.fetchDistinctIdValues(person)).toEqual(['anonymous_id', 'new_distinct_id'])
            expect(person.is_identified).toEqual(true)

            const result = await hub.db.postgresQuery(
                `SELECT "feature_flag_key", "person_id", "hash_key" FROM "posthog_featureflaghashkeyoverride" WHERE "team_id" = $1`,
                [teamId],
                'testQueryHashKeyOverride'
            )
            expect(result.rows).toEqual(
                expect.arrayContaining([
                    expect.objectContaining({
                        feature_flag_key: 'beta-feature',
                        person_id: person.id,
                        hash_key: expect.any(String), // either anon_id or identified_id
                    }),
                    {
                        feature_flag_key: 'multivariate-flag',
                        person_id: person.id,
                        hash_key: 'other_different_id',
                    },
                ])
            )
        })

        it('handles feature flag hash key overrides with no old overrides but existing new person overrides', async () => {
            const anonPerson = await hub.db.createPerson(
                timestamp.minus({ hours: 1 }),
                {},
                {},
                {},
                teamId,
                null,
                false,
                uuid.toString(),
                ['anonymous_id']
            )
            const identifiedPerson = await hub.db.createPerson(
                timestamp,
                {},
                {},
                {},
                teamId,
                null,
                false,
                uuid2.toString(),
                ['new_distinct_id']
            )

            await insertRow(hub.db.postgres, 'posthog_featureflaghashkeyoverride', {
                team_id: teamId,
                person_id: identifiedPerson.id,
                feature_flag_key: 'beta-feature',
                hash_key: 'example_id',
            })
            await insertRow(hub.db.postgres, 'posthog_featureflaghashkeyoverride', {
                team_id: teamId,
                person_id: identifiedPerson.id,
                feature_flag_key: 'multivariate-flag',
                hash_key: 'different_id',
            })

            await personState({
                event: '$identify',
                distinct_id: 'new_distinct_id',
                properties: {
                    $anon_distinct_id: 'anonymous_id',
                },
            }).update()
            await hub.db.kafkaProducer.flush()

            const [person] = await fetchPostgresPersons()
            expect([identifiedPerson.id, anonPerson.id]).toContain(person.id)
            expect(await hub.db.fetchDistinctIdValues(person)).toEqual(['anonymous_id', 'new_distinct_id'])
            expect(person.is_identified).toEqual(true)

            const result = await hub.db.postgresQuery(
                `SELECT "feature_flag_key", "person_id", "hash_key" FROM "posthog_featureflaghashkeyoverride" WHERE "team_id" = $1`,
                [teamId],
                'testQueryHashKeyOverride'
            )
            expect(result.rows).toEqual(
                expect.arrayContaining([
                    {
                        feature_flag_key: 'beta-feature',
                        person_id: person.id,
                        hash_key: 'example_id',
                    },
                    {
                        feature_flag_key: 'multivariate-flag',
                        person_id: person.id,
                        hash_key: 'different_id',
                    },
                ])
            )
        })
    })
    describe('on persons merges', () => {
        // For some reason these tests failed if I ran them with a hub shared
        // with other tests, so I'm creating a new hub for each test.
        let hub: Hub
        let closeHub: () => Promise<void>

        beforeEach(async () => {
            ;[hub, closeHub] = await createHub({})

            jest.spyOn(hub.personManager, 'isNewPerson')
            jest.spyOn(hub.db, 'fetchPerson')
            jest.spyOn(hub.db, 'updatePersonDeprecated')
        })

        afterEach(async () => {
            await closeHub()
        })

        function personState(event: Partial<PluginEvent>, person?: Person) {
            const fullEvent = {
                team_id: teamId,
                properties: {},
                ...event,
            }
            const personContainer = new LazyPersonContainer(teamId, event.distinct_id!, hub, person)
            return new PersonState(
                fullEvent as any,
                teamId,
                event.distinct_id!,
                timestamp,
                hub.db,
                hub.statsd,
                hub.personManager,
                personContainer,
                poEEmbraceJoin,
                uuid
            )
        }

        it('postgres and clickhouse get updated', async () => {
            const first: Person = await hub.db.createPerson(
                timestamp,
                {},
                {},
                {},
                teamId,
                null,
                false,
                uuid.toString(),
                ['first']
            )
            const second: Person = await hub.db.createPerson(
                timestamp,
                {},
                {},
                {},
                teamId,
                null,
                false,
                uuid2.toString(),
                ['second']
            )

            const state: PersonState = personState({}, first)
            jest.spyOn(hub.db.kafkaProducer, 'queueMessages')
            await state.mergePeople({
                mergeInto: first,
                mergeIntoDistinctId: 'first',
                otherPerson: second,
                otherPersonDistinctId: 'second',
            })
            await hub.db.kafkaProducer.flush()

            expect(hub.db.updatePersonDeprecated).toHaveBeenCalledTimes(1)
            expect(hub.db.kafkaProducer.queueMessages).toHaveBeenCalledTimes(1)
            // verify Postgres persons
            const persons = await fetchPostgresPersons()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid.toString(),
                    properties: {},
                    created_at: timestamp,
                    version: 1,
                    is_identified: true,
                })
            )

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining(['first', 'second']))

            // verify ClickHouse persons
            await delayUntilEventIngested(() => fetchPersonsRowsWithVersionHigerEqualThan(), 2) // wait until merge and delete processed
            const clickhousePersons = await fetchPersonsRows() // but verify full state
            expect(clickhousePersons).toEqual(
                expect.arrayContaining([
                    expect.objectContaining({
                        id: uuid.toString(),
                        properties: '{}',
                        created_at: timestampch,
                        version: 1,
                        is_identified: 1,
                    }),
                    expect.objectContaining({
                        id: uuid2.toString(),
                        is_deleted: 1,
                        version: 100,
                    }),
                ])
            )

            // verify ClickHouse distinct_ids
            await delayUntilEventIngested(() => fetchDistinctIdsClickhouseVersion1())
            const clickHouseDistinctIds = await fetchDistinctIdsClickhouse(persons[0])
            expect(clickHouseDistinctIds).toEqual(expect.arrayContaining(['first', 'second']))
        })
        it('throws if postgres unavailable', async () => {
            const first: Person = await hub.db.createPerson(
                timestamp,
                {},
                {},
                {},
                teamId,
                null,
                false,
                uuid.toString(),
                ['first']
            )
            const second: Person = await hub.db.createPerson(
                timestamp,
                {},
                {},
                {},
                teamId,
                null,
                false,
                uuid2.toString(),
                ['second']
            )

            const state: PersonState = personState({}, first)
            // break postgres
            const error = new DependencyUnavailableError('testing', 'Postgres', new Error('test'))
            jest.spyOn(hub.db, 'postgresTransaction').mockImplementation(() => {
                throw error
            })
            jest.spyOn(hub.db.kafkaProducer, 'queueMessages')
            await expect(
                state.mergePeople({
                    mergeInto: first,
                    mergeIntoDistinctId: 'first',
                    otherPerson: second,
                    otherPersonDistinctId: 'second',
                })
            ).rejects.toThrow(error)

            await hub.db.kafkaProducer.flush()

            expect(hub.db.postgresTransaction).toHaveBeenCalledTimes(1)
            expect(hub.db.kafkaProducer.queueMessages).not.toBeCalled()
            // verify Postgres persons
            const persons = await fetchPostgresPersons()
            expect(persons).toEqual(
                expect.arrayContaining([
                    expect.objectContaining({
                        id: expect.any(Number),
                        uuid: uuid.toString(),
                        properties: {},
                        created_at: timestamp,
                        version: 0,
                        is_identified: false,
                    }),
                    expect.objectContaining({
                        id: expect.any(Number),
                        uuid: uuid2.toString(),
                        properties: {},
                        created_at: timestamp,
                        version: 0,
                        is_identified: false,
                    }),
                ])
            )
        })
        it('retries merges up to retry limit if postgres down', async () => {
            const first: Person = await hub.db.createPerson(
                timestamp,
                {},
                {},
                {},
                teamId,
                null,
                false,
                uuid.toString(),
                ['first']
            )
            await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, uuid2.toString(), ['second'])

            const state: PersonState = personState({}, first)
            // break postgres
            const error = new DependencyUnavailableError('testing', 'Postgres', new Error('test'))
            jest.spyOn(state, 'mergePeople').mockImplementation(() => {
                throw error
            })
            jest.spyOn(hub.db.kafkaProducer, 'queueMessages')
            await expect(state.merge('second', 'first', teamId, timestamp, true)).rejects.toThrow(error)

            await hub.db.kafkaProducer.flush()

            expect(state.mergePeople).toHaveBeenCalledTimes(3)
            expect(hub.db.kafkaProducer.queueMessages).not.toBeCalled()
            // verify Postgres persons
            const persons = await fetchPostgresPersons()
            expect(persons).toEqual(
                expect.arrayContaining([
                    expect.objectContaining({
                        id: expect.any(Number),
                        uuid: uuid.toString(),
                        properties: {},
                        created_at: timestamp,
                        version: 0,
                        is_identified: false,
                    }),
                    expect.objectContaining({
                        id: expect.any(Number),
                        uuid: uuid2.toString(),
                        properties: {},
                        created_at: timestamp,
                        version: 0,
                        is_identified: false,
                    }),
                ])
            )
        })
    })

    describe('ageInMonthsLowCardinality', () => {
        beforeEach(() => {
            jest.setSystemTime(new Date('2022-03-15'))
        })
        it('gets the correct age in months', () => {
            let date = DateTime.fromISO('2022-01-16')
            expect(ageInMonthsLowCardinality(date)).toEqual(2)
            date = DateTime.fromISO('2022-01-14')
            expect(ageInMonthsLowCardinality(date)).toEqual(3)
            date = DateTime.fromISO('2021-11-25')
            expect(ageInMonthsLowCardinality(date)).toEqual(4)
        })
        it('returns 0 for future dates', () => {
            let date = DateTime.fromISO('2022-06-01')
            expect(ageInMonthsLowCardinality(date)).toEqual(0)
            date = DateTime.fromISO('2023-01-01')
            expect(ageInMonthsLowCardinality(date)).toEqual(0)
        })
        it('returns a low cardinality value', () => {
            let date = DateTime.fromISO('1990-01-01')
            expect(ageInMonthsLowCardinality(date)).toEqual(50)
            date = DateTime.fromMillis(0)
            expect(ageInMonthsLowCardinality(date)).toEqual(50)
        })
    })
})

describe('person id overrides', () => {
    // For some reason these tests failed if I ran them with a hub shared
    // with other tests, so I'm creating a new hub for each test.
    let hub: Hub
    let closeHub: () => Promise<void>
    let teamId: number
    const timestamp = DateTime.fromISO('2020-01-01T12:00:05.200Z').toUTC()

    beforeAll(async () => {
        ;[hub, closeHub] = await createHub({})
    })

    beforeEach(async () => {
        const organizationId = await createOrganization(hub.db.postgres)
        teamId = await createTeam(hub.db.postgres, organizationId)
        // jest.useFakeTimers({ advanceTimers: 50 })
    })

    afterEach(() => {
        jest.clearAllTimers()
    })

    afterAll(async () => {
        await closeHub()
    })

    async function updatePersonStateFromEvent(event: Partial<PluginEvent>, ts = '', mergeAttempts = 3) {
        const fullEvent = {
            team_id: teamId,
            properties: {},
            ...event,
        }
        const t = ts ? DateTime.fromISO(ts).toUTC() : timestamp
        const personContainer = new LazyPersonContainer(teamId, event.distinct_id!, hub)
        const state = new PersonState(
            fullEvent as any,
            teamId,
            event.distinct_id!,
            t,
            hub.db,
            hub.statsd,
            hub.personManager,
            personContainer,
            true,
            undefined,
            mergeAttempts
        )
        await state.update()
    }

    async function fetchPostgresPersons() {
        const query = `SELECT * FROM posthog_person WHERE team_id = ${teamId} ORDER BY id`
        return (await hub.db.postgres.query(query)).rows
    }

    async function fetchDistinctIds() {
        const result = await hub.db.postgres.query(
            `SELECT distinct_id, person_id FROM posthog_persondistinctid WHERE team_id=${teamId} ORDER BY id`
        )
        return result.rows.map(({ distinct_id, person_id }) => [distinct_id, person_id]).sort() as [string, string][]
    }

    async function fetchPersonIdOverrides() {
        const result = await hub.db.postgres.query(
            `SELECT old_person_id, override_person_id FROM posthog_personoverride WHERE team_id=${teamId} ORDER BY id`
        )
        return result.rows
            .map(({ old_person_id, override_person_id }) => [old_person_id, override_person_id])
            .sort() as [string, string][]
    }

    it('postgres overrides added on merge', async () => {
        await updatePersonStateFromEvent({
            event: 'event',
            distinct_id: 'first',
        })

        await updatePersonStateFromEvent({
            event: 'event',
            distinct_id: 'second',
        })

        const [first, second] = await fetchPostgresPersons()

        await updatePersonStateFromEvent({
            event: '$identify',
            distinct_id: 'first',
            properties: {
                $anon_distinct_id: 'second',
            },
        })

        // verify Postgres persons
        const persons = await fetchPostgresPersons()
        expect(persons).toEqual([
            expect.objectContaining({
                id: expect.any(Number),
                uuid: expect.any(String),
                properties: {},
                created_at: timestamp.toISO(),
                version: '1',
                is_identified: true,
            }),
        ])

        // verify Postgres distinct_ids
        const distinctIds = await fetchDistinctIds()
        expect(distinctIds).toEqual([
            ['first', persons[0].id],
            ['second', persons[0].id],
        ])

        // verify Postgres person_id overrides
        const overrides = await fetchPersonIdOverrides()
        expect(overrides).toEqual([[second.uuid, first.uuid]])

        // verify running merge again doesn't change the state
        await updatePersonStateFromEvent({
            event: '$identify',
            distinct_id: 'first',
            properties: {
                $anon_distinct_id: 'second',
            },
        })

        const personsAgain = await fetchPostgresPersons()
        const distinctIdsAgain = await fetchDistinctIds()
        const overridesAgain = await fetchPersonIdOverrides()

        expect(persons).toEqual(personsAgain)
        expect(distinctIds).toEqual(distinctIdsAgain)
        expect(overrides).toEqual(overridesAgain)
    })

    it('does not commit partial transactions on override conflicts', async () => {
        await updatePersonStateFromEvent({
            event: 'event',
            distinct_id: 'first',
        })

        await updatePersonStateFromEvent({
            event: 'event',
            distinct_id: 'second',
        })

        const [first, second] = await fetchPostgresPersons()

        const personsBeforeMergeAttempt = await fetchPostgresPersons()
        const distinctIdsBeforeMergeAttempt = await fetchDistinctIds()
        const overridesBeforeMergeAttempt = await fetchPersonIdOverrides()

        const originalPostgresQuery = hub.db.postgresQuery.bind(hub.db)
        const mockPostgresQuery = jest
            .spyOn(hub.db, 'postgresQuery')
            .mockImplementation(async (query: any, values: any[] | undefined, tag: string, ...args: any[]) => {
                if (tag === 'transitivePersonOverrides') {
                    throw new Error('Conflict')
                }
                return await originalPostgresQuery(query, values, tag, ...args)
            })

        await expect(
            updatePersonStateFromEvent({
                event: '$identify',
                distinct_id: 'first',
                properties: {
                    $anon_distinct_id: 'second',
                },
            })
        ).rejects.toThrow()

        // verify Postgres persons
        const personsAfterFailure = await fetchPostgresPersons()
        expect(personsAfterFailure).toEqual(
            personsBeforeMergeAttempt.map((person) =>
                expect.objectContaining({
                    id: person.id,
                    uuid: person.uuid,
                    properties: person.properties,
                    created_at: person.created_at,
                    // TODO: fix this. It seems that we update some person
                    // properties. In this case we'll raised an error,
                    // successfully updated distinct_ids and overrides but then
                    // will not send messages to Kafka. If there is logic that
                    // relies on e.g. is_identified being false, we will also
                    // end up not running the same logic even if we did have a
                    // retry.
                    // is_identified: person.is_identified,
                    // version: person.version,
                })
            )
        )

        // verify Postgres distinct_ids
        const distinctIdsAfterFailure = await fetchDistinctIds()
        expect(distinctIdsAfterFailure).toEqual(distinctIdsBeforeMergeAttempt)

        // verify Postgres person_id overrides
        const overridesAfterFailure = await fetchPersonIdOverrides()
        expect(overridesAfterFailure).toEqual(overridesBeforeMergeAttempt)

        // Now verify we successfully get to our target state if we do not have
        // any db errors.
        mockPostgresQuery.mockRestore()

        await updatePersonStateFromEvent({
            event: '$identify',
            distinct_id: 'first',
            properties: {
                $anon_distinct_id: 'second',
            },
        })

        // verify Postgres persons
        const persons = await fetchPostgresPersons()
        expect(persons).toEqual([
            expect.objectContaining({
                id: expect.any(Number),
                uuid: expect.any(String),
                properties: {},
                created_at: timestamp.toISO(),
                is_identified: true,
            }),
        ])

        // verify Postgres distinct_ids
        const distinctIds = await fetchDistinctIds()
        expect(distinctIds).toEqual([
            ['first', persons[0].id],
            ['second', persons[0].id],
        ])

        // verify Postgres person_id overrides
        const overrides = await fetchPersonIdOverrides()
        expect(overrides).toEqual([[second.uuid, first.uuid]])

        // verify running merge again doesn't change the state
        await updatePersonStateFromEvent({
            event: '$identify',
            distinct_id: 'first',
            properties: {
                $anon_distinct_id: 'second',
            },
        })
    })

    it('handles a chain of overrides being applied concurrently', async () => {
        await updatePersonStateFromEvent(
            {
                event: 'event',
                distinct_id: 'first',
                properties: {
                    $set: {
                        first: true,
                    },
                },
            },
            '2021-01-01T12:00:05.200Z'
        )

        await updatePersonStateFromEvent(
            {
                event: 'event',
                distinct_id: 'second',
                properties: {
                    $set: {
                        second: true,
                    },
                },
            },
            '2022-01-01T12:00:05.200Z'
        )

        await updatePersonStateFromEvent(
            {
                event: 'event',
                distinct_id: 'third',
                properties: {
                    $set: {
                        third: true,
                    },
                },
            },
            '2023-01-01T12:00:05.200Z'
        )

        const [first, second, third] = await fetchPostgresPersons()

        // We want to simulate a concurrent update to person_overrides. We do
        // this by first mocking the implementation to block at a certain point
        // in the transaction, then running the updatePersonStateFromEvent
        // function twice. We then wait for them to block before letting them
        // resume.
        let resumeExecution: (value: unknown) => void

        const postgresTransaction = hub.db.postgresTransaction.bind(hub.db)
        jest.spyOn(hub.db, 'postgresTransaction').mockImplementation(async (tag: string, transaction: any) => {
            if (tag === 'mergePeople') {
                return await postgresTransaction(tag, async (client) => {
                    if (resumeExecution) {
                        resumeExecution(undefined)
                    } else {
                        await new Promise((resolve) => {
                            resumeExecution = resolve
                        })
                    }

                    return await transaction(client)
                })
            } else {
                return await postgresTransaction(tag, transaction)
            }
        })

        // Due to usage of identify, the same distinct_id must be used as distinct_id, so
        // which ever order merges happen we will always be able to merge and not be blocked
        // due to the mergefrom user being already identified
        // To create a chain we ideally want the merges to be A -> B -> C. Which person we
        // merge into is determined by the creation timestamps (merging into oldest)
        await expect(
            Promise.all([
                updatePersonStateFromEvent(
                    {
                        event: '$identify',
                        distinct_id: 'second',
                        properties: {
                            $anon_distinct_id: 'third',
                        },
                    },
                    '',
                    0
                ),
                updatePersonStateFromEvent(
                    {
                        event: '$identify',
                        distinct_id: 'second',
                        properties: {
                            $anon_distinct_id: 'first',
                        },
                    },
                    '',
                    0
                ),
            ])
        ).rejects.toThrow()

        await Promise.all([
            updatePersonStateFromEvent({
                event: '$identify',
                distinct_id: 'second',
                properties: {
                    $anon_distinct_id: 'third',
                },
            }),
            updatePersonStateFromEvent({
                event: '$identify',
                distinct_id: 'second',
                properties: {
                    $anon_distinct_id: 'first',
                },
            }),
        ])

        // verify Postgres persons
        const personsAfterFailure = await fetchPostgresPersons()
        expect(personsAfterFailure).toEqual([
            expect.objectContaining({
                id: first.id, // guaranteed to merge into first due to created_at timestamps
                uuid: first.uuid,
                properties: { first: true, second: true, third: true },
                created_at: first.created_at,
                is_identified: true,
                version: '1', // the test intends for it to be a chain, so must get v1, we get v2 if second->first and third->first, but we want it to be third->second->first
            }),
        ])

        // verify Postgres distinct_ids
        const distinctIdsAfterFailure = await fetchDistinctIds()
        expect(distinctIdsAfterFailure).toEqual([
            ['first', first.id],
            ['second', first.id],
            ['third', first.id],
        ])

        // verify Postgres person_id overrides
        const overridesfterFailure = await fetchPersonIdOverrides()
        expect(overridesfterFailure).toEqual([
            [second.uuid, first.uuid],
            [third.uuid, first.uuid],
        ])
    })

    it('handles a chain of overrides being applied out of order', async () => {
        await updatePersonStateFromEvent({
            event: 'event',
            distinct_id: 'first',
        })

        await updatePersonStateFromEvent({
            event: 'event',
            distinct_id: 'second',
        })

        await updatePersonStateFromEvent({
            event: 'event',
            distinct_id: 'third',
        })

        const [first, second, third] = await fetchPostgresPersons()

        await updatePersonStateFromEvent({
            event: '$identify',
            distinct_id: 'third',
            properties: {
                $anon_distinct_id: 'second',
            },
        })

        await updatePersonStateFromEvent({
            event: '$identify',
            distinct_id: 'second',
            properties: {
                $anon_distinct_id: 'first',
            },
        })

        // verify Postgres persons
        const personsAfterFailure = await fetchPostgresPersons()
        expect(personsAfterFailure).toEqual([
            expect.objectContaining({
                id: third.id,
                uuid: third.uuid,
                properties: {},
                created_at: third.created_at,
                // TODO: fix this. It seems that we update some person
                // properties. In this case we'll raised an error,
                // successfully updated distinct_ids and overrides but then
                // will not send messages to Kafka. If there is logic that
                // relies on e.g. is_identified being false, we will also
                // end up not running the same logic even if we did have a
                // retry.
                // is_identified: person.is_identified,
                // version: person.version,
            }),
        ])

        // verify Postgres distinct_ids
        const distinctIdsAfterFailure = await fetchDistinctIds()
        expect(distinctIdsAfterFailure).toEqual([
            ['first', third.id],
            ['second', third.id],
            ['third', third.id],
        ])

        // verify Postgres person_id overrides
        const overridesfterFailure = await fetchPersonIdOverrides()
        expect(overridesfterFailure).toEqual([
            [first.uuid, third.uuid],
            [second.uuid, third.uuid],
        ])
    })
})
