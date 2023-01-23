import { PluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'
import { DatabaseError } from 'pg'
import tk from 'timekeeper'

import { Database, Hub, Person } from '../../../src/types'
import { createHub } from '../../../src/utils/db/hub'
import { UUIDT } from '../../../src/utils/utils'
import { LazyPersonContainer } from '../../../src/worker/ingestion/lazy-person-container'
import { ageInMonthsLowCardinality, PersonState } from '../../../src/worker/ingestion/person-state'
import { delayUntilEventIngested, resetTestDatabaseClickhouse } from '../../helpers/clickhouse'
import { createUserTeamAndOrganization, insertRow, resetTestDatabase } from '../../helpers/sql'

jest.mock('../../../src/utils/status')
jest.setTimeout(60000) // 60 sec timeout

const timestamp = DateTime.fromISO('2020-01-01T12:00:05.200Z').toUTC()
const timestamp2 = DateTime.fromISO('2020-02-02T12:00:05.200Z').toUTC()
const timestampch = '2020-01-01 12:00:05.000'

describe('PersonState.update()', () => {
    let hub: Hub
    let closeHub: () => Promise<void>

    let uuid: UUIDT
    let uuid2: UUIDT
    let teamId = 10 // Incremented every test. Avoids late ingestion causing issues

    beforeEach(async () => {
        uuid = new UUIDT()
        uuid2 = new UUIDT()
        teamId++
        ;[hub, closeHub] = await createHub({})
        await Promise.all([
            resetTestDatabase(),
            resetTestDatabaseClickhouse(),
            // Avoid collapsing merge tree causing race conditions in tests!
            hub.db.clickhouseQuery('SYSTEM STOP MERGES'),
        ])
        await createUserTeamAndOrganization(
            hub.db.postgres,
            teamId,
            teamId,
            new UUIDT().toString(),
            new UUIDT().toString(),
            new UUIDT().toString()
        )

        jest.spyOn(hub.personManager, 'isNewPerson')
        jest.spyOn(hub.db, 'fetchPerson')
        jest.spyOn(hub.db, 'updatePersonDeprecated')
    })

    afterEach(async () => {
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
            uuid
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
            const persons = await hub.db.fetchPersons()
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
            const persons = await hub.db.fetchPersons()
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
            const persons = await hub.db.fetchPersons()
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
            const persons = await hub.db.fetchPersons()
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
            const persons = await hub.db.fetchPersons()
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
            const persons = await hub.db.fetchPersons()
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
            const persons = await hub.db.fetchPersons()
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
            const persons = await hub.db.fetchPersons()
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
            const persons = await hub.db.fetchPersons()
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
            const persons = await hub.db.fetchPersons()
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
            const persons = await hub.db.fetchPersons()
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
            const persons = await hub.db.fetchPersons()
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
            const persons = await hub.db.fetchPersons()
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
            const persons = await hub.db.fetchPersons()
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
            const persons = await hub.db.fetchPersons()
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
            const persons = await hub.db.fetchPersons()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid2.toString(),
                    properties: {},
                    created_at: timestamp,
                    version: 1,
                    is_identified: true,
                })
            )

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
                        id: uuid2.toString(),
                        properties: '{}',
                        created_at: timestampch,
                        version: 1,
                        is_identified: 1,
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
            const persons = await hub.db.fetchPersons()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid2.toString(),
                    properties: {},
                    created_at: timestamp,
                    version: 1,
                    is_identified: true,
                })
            )

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
                        id: uuid2.toString(),
                        properties: '{}',
                        created_at: timestampch,
                        version: 1,
                        is_identified: 1,
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
            const persons = (await hub.db.fetchPersons()).sort((a, b) => a.id - b.id)
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
            const persons = (await hub.db.fetchPersons()).sort((a, b) => a.id - b.id)
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
            await hub.db.createPerson(timestamp, { b: 3, c: 4, d: 5 }, {}, {}, teamId, null, false, uuid2.toString(), [
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
            const persons = await hub.db.fetchPersons()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid2.toString(),
                    properties: { a: 1, b: 3, c: 4, d: 6, e: 7, f: 9 },
                    created_at: timestamp,
                    version: 1,
                    is_identified: true,
                })
            )

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
                        id: uuid2.toString(),
                        properties: JSON.stringify({ a: 1, b: 3, c: 4, d: 6, e: 7, f: 9 }),
                        created_at: timestampch,
                        version: 1,
                        is_identified: 1,
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
            const persons = await hub.db.fetchPersons()
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
            const persons = await hub.db.fetchPersons()
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
            const persons = await hub.db.fetchPersons()
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
            const persons = await hub.db.fetchPersons()
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
            const persons = await hub.db.fetchPersons()
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
            const persons = await hub.db.fetchPersons()
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
            const persons = await hub.db.fetchPersons()
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
            const persons = await hub.db.fetchPersons()
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
            const persons = (await hub.db.fetchPersons()).sort((a, b) => a.id - b.id)
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
            const persons = await hub.db.fetchPersons()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid2.toString(),
                    properties: {},
                    created_at: timestamp,
                    version: 1,
                    is_identified: true,
                })
            )

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
                        id: uuid2.toString(),
                        properties: '{}',
                        created_at: timestampch,
                        version: 1,
                        is_identified: 1,
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
            const persons = await hub.db.fetchPersons()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid2.toString(),
                    properties: {},
                    created_at: timestamp,
                    version: 1,
                    is_identified: true,
                })
            )

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
                        id: uuid2.toString(),
                        properties: '{}',
                        created_at: timestampch,
                        version: 1,
                        is_identified: 1,
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

        it('merge into distinct_id person and updates properties with $set/$set_once', async () => {
            await hub.db.createPerson(timestamp, { a: 1, b: 2 }, {}, {}, teamId, null, false, uuid.toString(), [
                'old-user',
            ])
            await hub.db.createPerson(timestamp, { b: 3, c: 4, d: 5 }, {}, {}, teamId, null, false, uuid2.toString(), [
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
            const persons = await hub.db.fetchPersons()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid2.toString(),
                    properties: { a: 1, b: 3, c: 4, d: 6, e: 7, f: 9 },
                    created_at: timestamp,
                    version: 1,
                    is_identified: true,
                })
            )

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
                        id: uuid2.toString(),
                        properties: JSON.stringify({ a: 1, b: 3, c: 4, d: 6, e: 7, f: 9 }),
                        created_at: timestampch,
                        version: 1,
                        is_identified: 1,
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

            const persons = await hub.db.fetchPersons()
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

            const persons = await hub.db.fetchPersons()
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

            const persons = await hub.db.fetchPersons()
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

            const persons = await hub.db.fetchPersons()
            expect(persons.length).toEqual(1)

            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining(['some_distinct_id']))
            expect(hub.statsd!.increment).toHaveBeenCalledWith('illegal_distinct_ids.total', { distinctId: 'null' })
        })
    })

    describe('foreign key updates in other tables', () => {
        it('handles feature flag hash key overrides with no conflicts', async () => {
            const anonPerson = await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, uuid.toString(), [
                'anonymous_id',
            ])
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
                person_id: anonPerson.id,
                feature_flag_key: 'multivariate-flag',
                hash_key: 'example_id',
            })

            // this event means the `anonPerson` will be deleted
            // so hashkeyoverride should be updated to `identifiedPerson`'s id
            await personState({
                event: '$identify',
                distinct_id: 'new_distinct_id',
                properties: {
                    $anon_distinct_id: 'anonymous_id',
                    distinct_id: 'new_distinct_id',
                },
            }).update()
            await hub.db.kafkaProducer.flush()

            const [person] = await hub.db.fetchPersons()
            expect(person.id).toEqual(identifiedPerson.id)
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
                        person_id: identifiedPerson.id,
                        hash_key: 'example_id',
                    },
                    {
                        feature_flag_key: 'multivariate-flag',
                        person_id: identifiedPerson.id,
                        hash_key: 'example_id',
                    },
                ])
            )
        })

        it('handles feature flag hash key overrides with some conflicts handled gracefully', async () => {
            const anonPerson = await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, uuid.toString(), [
                'anonymous_id',
            ])
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
            // which implies a clash when anonPerson is deleted
            await insertRow(hub.db.postgres, 'posthog_featureflaghashkeyoverride', {
                team_id: teamId,
                person_id: anonPerson.id,
                feature_flag_key: 'beta-feature',
                hash_key: 'example_id',
            })
            await insertRow(hub.db.postgres, 'posthog_featureflaghashkeyoverride', {
                team_id: teamId,
                person_id: identifiedPerson.id,
                feature_flag_key: 'beta-feature',
                hash_key: 'different_id',
            })
            await insertRow(hub.db.postgres, 'posthog_featureflaghashkeyoverride', {
                team_id: teamId,
                person_id: anonPerson.id,
                feature_flag_key: 'multivariate-flag',
                hash_key: 'other_different_id',
            })

            // this event means the `anonPerson` will be deleted
            // so hashkeyoverride should be updated to `identifiedPerson`'s id
            await personState({
                event: '$identify',
                distinct_id: 'new_distinct_id',
                properties: {
                    $anon_distinct_id: 'anonymous_id',
                    distinct_id: 'new_distinct_id',
                },
            }).update()
            await hub.db.kafkaProducer.flush()

            const [person] = await hub.db.fetchPersons()
            expect(person.id).toEqual(identifiedPerson.id)
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
                        person_id: identifiedPerson.id,
                        hash_key: 'different_id', // wasn't overriden from anon flag, because override already exists
                    },
                    {
                        feature_flag_key: 'multivariate-flag',
                        person_id: identifiedPerson.id,
                        hash_key: 'other_different_id',
                    },
                ])
            )
        })

        it('handles feature flag hash key overrides with no old overrides but existing new person overrides', async () => {
            await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, uuid.toString(), ['anonymous_id'])
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

            const [person] = await hub.db.fetchPersons()
            expect(person.id).toEqual(identifiedPerson.id)
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
                        person_id: identifiedPerson.id,
                        hash_key: 'example_id',
                    },
                    {
                        feature_flag_key: 'multivariate-flag',
                        person_id: identifiedPerson.id,
                        hash_key: 'different_id',
                    },
                ])
            )
        })
    })
    describe('on persons merges', () => {
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
            jest.spyOn(state, 'aliasDeprecated').mockImplementation()
            await state.mergePeople({
                mergeInto: first,
                mergeIntoDistinctId: 'first',
                otherPerson: second,
                otherPersonDistinctId: 'second',
                timestamp: timestamp,
                totalMergeAttempts: 0,
            })
            await hub.db.kafkaProducer.flush()

            expect(hub.db.updatePersonDeprecated).toHaveBeenCalledTimes(1)
            expect(state.aliasDeprecated).not.toHaveBeenCalled()
            expect(hub.db.kafkaProducer.queueMessages).toHaveBeenCalledTimes(1)
            // verify Postgres persons
            const persons = await hub.db.fetchPersons()
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
            expect(clickhousePersons.length).toEqual(2)
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
        it('first failure is retried', async () => {
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
            const error = new DatabaseError('testing', 1, 'error')
            jest.spyOn(hub.db, 'updatePersonDeprecated').mockImplementation(() => {
                throw error
            })
            jest.spyOn(hub.db.kafkaProducer, 'queueMessages')
            jest.spyOn(state, 'aliasDeprecated').mockImplementation()
            await state.mergePeople({
                mergeInto: first,
                mergeIntoDistinctId: 'first',
                otherPerson: second,
                otherPersonDistinctId: 'second',
                timestamp: timestamp,
                totalMergeAttempts: 0,
            })

            await hub.db.kafkaProducer.flush()

            expect(hub.db.updatePersonDeprecated).toHaveBeenCalledTimes(1)
            expect(state.aliasDeprecated).toHaveBeenCalledTimes(1)
            expect(hub.db.kafkaProducer.queueMessages).not.toBeCalled()
            // verify Postgres persons
            const persons = await hub.db.fetchPersons()
            expect(persons.length).toEqual(2)
        })

        it('throws if retry limits hit', async () => {
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
            const error = new DatabaseError('testing', 1, 'error')
            jest.spyOn(hub.db, 'updatePersonDeprecated').mockImplementation(() => {
                throw error
            })
            jest.spyOn(hub.db.kafkaProducer, 'queueMessages')
            jest.spyOn(state, 'aliasDeprecated').mockImplementation()
            await expect(
                state.mergePeople({
                    mergeInto: first,
                    mergeIntoDistinctId: 'first',
                    otherPerson: second,
                    otherPersonDistinctId: 'second',
                    timestamp: timestamp,
                    totalMergeAttempts: 2, // Retry limit hit
                })
            ).rejects.toThrow(error)

            await hub.db.kafkaProducer.flush()

            expect(hub.db.updatePersonDeprecated).toHaveBeenCalledTimes(1)
            expect(state.aliasDeprecated).not.toHaveBeenCalled()
            expect(hub.db.kafkaProducer.queueMessages).not.toBeCalled()
            // verify Postgres persons
            const persons = await hub.db.fetchPersons()
            expect(persons.length).toEqual(2)
        })
    })

    describe('ageInMonthsLowCardinality', () => {
        beforeEach(() => {
            tk.freeze(new Date('2022-03-15'))
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
