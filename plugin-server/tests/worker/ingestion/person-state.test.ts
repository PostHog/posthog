import { PluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { Database, Hub, Person } from '../../../src/types'
import { createHub } from '../../../src/utils/db/hub'
import { UUIDT } from '../../../src/utils/utils'
import { LazyPersonContainer } from '../../../src/worker/ingestion/lazy-person-container'
import { PersonState } from '../../../src/worker/ingestion/person-state'
import { delayUntilEventIngested, resetTestDatabaseClickhouse } from '../../helpers/clickhouse'
import { insertRow, resetTestDatabase } from '../../helpers/sql'

jest.mock('../../../src/utils/status')
jest.setTimeout(60000) // 60 sec timeout

const timestamp = DateTime.fromISO('2020-01-01T12:00:05.200Z').toUTC()
const timestamp2 = DateTime.fromISO('2020-02-02T12:00:05.200Z').toUTC()
const timestampch = '2020-01-01 12:00:05.000'
const timestamp2ch = '2020-02-02 12:00:05.000'

describe('PersonState.update()', () => {
    let hub: Hub
    let closeHub: () => Promise<void>

    let uuid: UUIDT
    let uuid2: UUIDT

    beforeEach(async () => {
        uuid = new UUIDT()
        uuid2 = new UUIDT()

        await resetTestDatabase()
        await resetTestDatabaseClickhouse()
        ;[hub, closeHub] = await createHub({})
        // Avoid collapsing merge tree causing race conditions!
        await hub.db.clickhouseQuery('SYSTEM STOP MERGES')

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
            team_id: 2,
            properties: {},
            ...event,
        }
        const personContainer = new LazyPersonContainer(2, event.distinct_id!, hub, person)
        return new PersonState(
            fullEvent as any,
            2,
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
        const query = `SELECT * FROM person FINAL order by _offset`
        return (await hub.db.clickhouseQuery(query)).data
    }

    async function fetchDistinctIdsRows() {
        const query = `SELECT * FROM person_distinct_id2 FINAL`
        return (await hub.db.clickhouseQuery(query)).data
    }

    describe('on person creation', () => {
        it('creates person if they are new', async () => {
            const personContainer = await personState({ event: '$pageview', distinct_id: 'new-user' }).update()
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
            expect(persons[0]).toEqual(await personContainer.get())

            // Make sure Kafka messages are processed before CH db reset
            const clickhouseRows = await delayUntilEventIngested(fetchPersonsRows)
            expect(clickhouseRows.length).toEqual(1)
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

            // Make sure Kafka messages are processed before CH db reset
            const clickhouseRows = await delayUntilEventIngested(fetchPersonsRows)
            expect(clickhouseRows.length).toEqual(1)
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

            // Make sure Kafka messages are processed before CH db reset
            const clickhouseRows = await delayUntilEventIngested(fetchPersonsRows)
            expect(clickhouseRows.length).toEqual(1)
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

            // Make sure Kafka messages are processed before CH db reset
            const clickhouseRows = await delayUntilEventIngested(fetchPersonsRows)
            expect(clickhouseRows.length).toEqual(1)
        })
    })

    describe('on person update', () => {
        it('updates person properties', async () => {
            await hub.db.createPerson(timestamp, { b: 3, c: 4 }, {}, {}, 2, null, false, uuid.toString(), ['new-user'])

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

            // Make sure Kafka messages are processed before CH db reset
            const clickhouseRows = await delayUntilEventIngested(fetchPersonsRows)
            expect(clickhouseRows.length).toEqual(1)
        })

        it('updating with cached person data skips checking if person is new', async () => {
            const person = await hub.db.createPerson(
                timestamp,
                { b: 3, c: 4 },
                {},
                {},
                2,
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

            // Make sure Kafka messages are processed before CH db reset
            const clickhouseRows = await delayUntilEventIngested(fetchPersonsRows)
            expect(clickhouseRows.length).toEqual(1)
        })

        it('does not update person if not needed', async () => {
            await hub.db.createPerson(timestamp, { b: 3, c: 4 }, {}, {}, 2, null, false, uuid.toString(), ['new-user'])

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
                    version: 0, // note version doesn't change
                    is_identified: false,
                })
            )

            // verify personContainer
            expect(persons[0]).toEqual(await personContainer.get())

            // Make sure Kafka messages are processed before CH db reset
            const clickhouseRows = await delayUntilEventIngested(fetchPersonsRows)
            expect(clickhouseRows.length).toEqual(1)
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

            // Make sure Kafka messages are processed before CH db reset
            const clickhouseRows = await delayUntilEventIngested(fetchPersonsRows)
            expect(clickhouseRows.length).toEqual(1)
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

            // Make sure Kafka messages are processed before CH db reset
            const clickhouseRows = await delayUntilEventIngested(fetchPersonsRows)
            expect(clickhouseRows.length).toEqual(1)
        })

        it('updates person properties leaves is_identified false when no change to distinct_ids', async () => {
            await hub.db.createPerson(timestamp, { b: 3, c: 4 }, {}, {}, 2, null, false, uuid.toString(), ['new-user'])

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

            // Make sure Kafka messages are processed before CH db reset
            const clickhouseRows = await delayUntilEventIngested(fetchPersonsRows)
            expect(clickhouseRows.length).toEqual(1)
        })

        it('marks user as is_identified when no change to distinct_ids when $anon_distinct_id passed', async () => {
            // TODO: current code does so, but we shouldn't
            await hub.db.createPerson(timestamp, {}, {}, {}, 2, null, false, uuid.toString(), ['new-user', 'old-user'])

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

            // Make sure Kafka messages are processed before CH db reset
            const clickhouseRows = await delayUntilEventIngested(fetchPersonsRows)
            expect(clickhouseRows.length).toEqual(1)
        })

        it('does not update person if no change to is_identified nor properties', async () => {
            await hub.db.createPerson(timestamp, { b: 3, c: 4 }, {}, {}, 2, null, true, uuid.toString(), [
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
                    version: 0, // note version doesn't change
                    is_identified: true,
                })
            )

            // verify personContainer
            expect(persons[0]).toEqual(await personContainer.get())

            // Make sure Kafka messages are processed before CH db reset
            const clickhouseRows = await delayUntilEventIngested(fetchPersonsRows)
            expect(clickhouseRows.length).toEqual(1)
        })

        it('add distinct id and marks user is_identified when passed $anon_distinct_id person does not exists and distinct_id does', async () => {
            await hub.db.createPerson(timestamp, {}, {}, {}, 2, null, false, uuid.toString(), ['new-user'])

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

            // Make sure Kafka messages are processed before CH db reset
            await delayUntilEventIngested(fetchPersonsRows)
        })

        it('add distinct id and marks user as is_identified when passed $anon_distinct_id person exists and distinct_id does not', async () => {
            await hub.db.createPerson(timestamp, {}, {}, {}, 2, null, false, uuid.toString(), ['old-user'])

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

            // Make sure Kafka messages are processed before CH db reset
            await delayUntilEventIngested(fetchPersonsRows)
        })

        it('add distinct id, marks user as is_identified and updates properties when one of the persons exists and properties are passed', async () => {
            await hub.db.createPerson(timestamp, { b: 3, c: 4 }, {}, {}, 2, null, false, uuid.toString(), ['new-user'])

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

            // Make sure Kafka messages are processed before CH db reset
            await delayUntilEventIngested(fetchPersonsRows)
        })

        it('merges people and marks user as is_identified when both persons have is_identified false', async () => {
            await hub.db.createPerson(timestamp, {}, {}, {}, 2, null, false, uuid.toString(), ['old-user'])
            await hub.db.createPerson(timestamp2, {}, {}, {}, 2, null, false, uuid2.toString(), ['new-user'])

            const personContainer = await personState({
                event: '$identify',
                distinct_id: 'new-user', // note we merge into this person and that's important
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
            const clickhousePersons = await delayUntilEventIngested(() => fetchPersonsRows(), 2)
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
            await delayUntilEventIngested(fetchDistinctIdsRows)
            const clickHouseDistinctIds = await hub.db.fetchDistinctIdValues(persons[0], Database.ClickHouse)
            expect(clickHouseDistinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))

            // verify personContainer
            expect(persons[0]).toEqual(await personContainer.get())
        })

        it('merges people and marks user as is_identified when distinct_id user is identified and $anon_distinct_id user is not', async () => {
            await hub.db.createPerson(timestamp, {}, {}, {}, 2, null, false, uuid.toString(), ['old-user'])
            await hub.db.createPerson(timestamp2, {}, {}, {}, 2, null, true, uuid2.toString(), ['new-user'])

            const personContainer = await personState({
                event: '$identify',
                distinct_id: 'new-user', // note we merge into this person and that's important
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
            const clickhousePersons = await delayUntilEventIngested(() => fetchPersonsRows(), 2)
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
            await delayUntilEventIngested(fetchDistinctIdsRows)
            const clickHouseDistinctIds = await hub.db.fetchDistinctIdValues(persons[0], Database.ClickHouse)
            expect(clickHouseDistinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))

            // verify personContainer
            expect(persons[0]).toEqual(await personContainer.get())
        })

        it('does not merge people and leaves is_identified unchanged when distinct_id user is not identified and $anon_distinct_id user is', async () => {
            await hub.db.createPerson(timestamp, {}, {}, {}, 2, null, true, uuid.toString(), ['old-user'])
            await hub.db.createPerson(timestamp2, {}, {}, {}, 2, null, false, uuid2.toString(), ['new-user'])

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
                    is_identified: true, // TODO: we don't want this person to be updated, but the current code does so
                })
            )

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining(['old-user']))
            const distinctIds2 = await hub.db.fetchDistinctIdValues(persons[1])
            expect(distinctIds2).toEqual(expect.arrayContaining(['new-user']))

            // verify ClickHouse persons
            const clickhousePersons = await delayUntilEventIngested(() => fetchPersonsRows(), 2)
            expect(clickhousePersons.length).toEqual(2)
            expect(clickhousePersons[0]).toEqual(
                expect.objectContaining({
                    id: uuid.toString(),
                    properties: '{}',
                    created_at: timestampch,
                    version: 0,
                    is_identified: 1,
                })
            )
            expect(clickhousePersons[1]).toEqual(
                expect.objectContaining({
                    id: uuid2.toString(),
                    properties: '{}',
                    created_at: timestamp2ch,
                    version: 1,
                    is_identified: 1,
                })
            )

            // verify ClickHouse distinct_ids
            await delayUntilEventIngested(() => fetchDistinctIdsRows(), 2)
            const clickHouseDistinctIds = await hub.db.fetchDistinctIdValues(persons[0], Database.ClickHouse)
            expect(clickHouseDistinctIds).toEqual(expect.arrayContaining(['old-user']))
            const clickHouseDistinctIds2 = await hub.db.fetchDistinctIdValues(persons[1], Database.ClickHouse)
            expect(clickHouseDistinctIds2).toEqual(expect.arrayContaining(['new-user']))

            // verify personContainer
            expect(persons[1]).toEqual(await personContainer.get())
        })

        it('does not merge people when both users are identified', async () => {
            await hub.db.createPerson(timestamp, {}, {}, {}, 2, null, true, uuid.toString(), ['old-user'])
            await hub.db.createPerson(timestamp2, {}, {}, {}, 2, null, true, uuid2.toString(), ['new-user'])

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

            // verify ClickHouse persons
            const clickhousePersons = await delayUntilEventIngested(() => fetchPersonsRows(), 2)
            expect(clickhousePersons.length).toEqual(2)
            expect(clickhousePersons[0]).toEqual(
                expect.objectContaining({
                    id: uuid.toString(),
                    properties: '{}',
                    created_at: timestampch,
                    version: 0,
                    is_identified: 1,
                })
            )
            expect(clickhousePersons[1]).toEqual(
                expect.objectContaining({
                    id: uuid2.toString(),
                    properties: '{}',
                    created_at: timestamp2ch,
                    version: 0,
                    is_identified: 1,
                })
            )

            // verify ClickHouse distinct_ids
            await delayUntilEventIngested(() => fetchDistinctIdsRows(), 2)
            const clickHouseDistinctIds = await hub.db.fetchDistinctIdValues(persons[0], Database.ClickHouse)
            expect(clickHouseDistinctIds).toEqual(expect.arrayContaining(['old-user']))
            const clickHouseDistinctIds2 = await hub.db.fetchDistinctIdValues(persons[1], Database.ClickHouse)
            expect(clickHouseDistinctIds2).toEqual(expect.arrayContaining(['new-user']))

            // verify personContainer
            expect(persons[1]).toEqual(await personContainer.get())
        })

        it('merges people and updates properties with $set/$set_once', async () => {
            await hub.db.createPerson(timestamp, { a: 1, b: 2 }, {}, {}, 2, null, false, uuid.toString(), ['old-user'])
            await hub.db.createPerson(timestamp, { b: 3, c: 4, d: 5 }, {}, {}, 2, null, false, uuid2.toString(), [
                'new-user',
            ])

            const personContainer = await personState({
                event: '$identify',
                distinct_id: 'new-user', // note we merge into this person and that's important
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
            const clickhousePersons = await delayUntilEventIngested(() => fetchPersonsRows(), 2)
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
            await delayUntilEventIngested(fetchDistinctIdsRows)
            const clickHouseDistinctIds = await hub.db.fetchDistinctIdValues(persons[0], Database.ClickHouse)
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
                2,
                null,
                false,
                uuid.toString(),
                ['old-user']
            )
            await hub.db.createPerson(timestamp, {}, {}, {}, 2, null, false, uuid2.toString(), ['new-user'])
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

            console.log('---')
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
            const clickhousePersons = await delayUntilEventIngested(() => fetchPersonsRows(), 2)
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
            await delayUntilEventIngested(fetchDistinctIdsRows)
            const clickHouseDistinctIds = await hub.db.fetchDistinctIdValues(persons[0], Database.ClickHouse)
            expect(clickHouseDistinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))

            // verify personContainer
            expect(persons[0]).toEqual(await personContainer.get())
        })
    })

    describe('on $create_alias event', () => {
        it('creates person', async () => {
            // same as $identify > creates person with anon_distinct_id'
            const personContainer = await personState({
                event: '$create_alias',
                distinct_id: 'new-user',
                properties: {
                    $set: { foo: 'bar' },
                    alias: 'old-user',
                },
            }).update()

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
                    is_identified: false, // TODO: different from identify
                })
            )

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))

            // verify ClickHouse persons
            const clickhousePersons = await delayUntilEventIngested(fetchPersonsRows)
            expect(clickhousePersons.length).toEqual(1)
            expect(clickhousePersons[0]).toEqual(
                expect.objectContaining({
                    id: uuid.toString(),
                    properties: JSON.stringify({ foo: 'bar' }),
                    created_at: timestampch,
                    version: 0,
                    is_identified: 0,
                })
            )

            // verify ClickHouse distinct_ids
            await delayUntilEventIngested(fetchDistinctIdsRows)
            const clickHouseDistinctIds = await hub.db.fetchDistinctIdValues(persons[0], Database.ClickHouse)
            expect(clickHouseDistinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))

            // verify personContainer
            expect(persons[0]).toEqual(await personContainer.get())
        })

        it('add distinct id while anon person does not exists', async () => {
            await hub.db.createPerson(timestamp, {}, {}, {}, 2, null, false, uuid.toString(), ['new-user'])

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
                    version: 0,
                    is_identified: false, // TODO: different
                })
            )

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))

            // verify ClickHouse persons
            const clickhousePersons = await delayUntilEventIngested(() => fetchPersonsRows(), 2)
            expect(clickhousePersons.length).toEqual(1)
            expect(clickhousePersons[0]).toEqual(
                expect.objectContaining({
                    id: uuid.toString(),
                    properties: '{}',
                    created_at: timestampch,
                    version: 0,
                    is_identified: 0,
                })
            )

            // verify ClickHouse distinct_ids
            await delayUntilEventIngested(fetchDistinctIdsRows)
            const clickHouseDistinctIds = await hub.db.fetchDistinctIdValues(persons[0], Database.ClickHouse)
            expect(clickHouseDistinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))

            // verify personContainer
            expect(persons[0]).toEqual(await personContainer.get())
        })

        it('add distinct id while only anon person exists', async () => {
            await hub.db.createPerson(timestamp, {}, {}, {}, 2, null, false, uuid.toString(), ['old-user'])

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
                    version: 0,
                    is_identified: false,
                })
            )

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))

            // verify ClickHouse persons
            const clickhousePersons = await delayUntilEventIngested(fetchPersonsRows)
            expect(clickhousePersons.length).toEqual(1)
            expect(clickhousePersons[0]).toEqual(
                expect.objectContaining({
                    id: uuid.toString(),
                    properties: '{}',
                    created_at: timestampch,
                    version: 0,
                    is_identified: 0,
                })
            )

            // verify ClickHouse distinct_ids
            await delayUntilEventIngested(fetchDistinctIdsRows)
            const clickHouseDistinctIds = await hub.db.fetchDistinctIdValues(persons[0], Database.ClickHouse)
            expect(clickHouseDistinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))

            // verify personContainer
            expect(persons[0]).toEqual(await personContainer.get())
        })

        it('merges people when neither identified', async () => {
            await hub.db.createPerson(timestamp, {}, {}, {}, 2, null, false, uuid.toString(), ['old-user'])
            await hub.db.createPerson(timestamp2, {}, {}, {}, 2, null, false, uuid2.toString(), ['new-user'])

            const personContainer = await personState({
                event: '$create_alias',
                distinct_id: 'new-user', // note we merge into this person and that's important
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
                    is_identified: false, // TODO: different from $identify
                })
            )

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))

            // verify ClickHouse persons
            const clickhousePersons = await delayUntilEventIngested(() => fetchPersonsRows(), 2)
            expect(clickhousePersons.length).toEqual(2)
            expect(clickhousePersons).toEqual(
                expect.arrayContaining([
                    expect.objectContaining({
                        id: uuid2.toString(),
                        properties: '{}',
                        created_at: timestampch,
                        version: 1,
                        is_identified: 0,
                    }),
                    expect.objectContaining({
                        id: uuid.toString(),
                        is_deleted: 1,
                        version: 100,
                    }),
                ])
            )

            // verify ClickHouse distinct_ids
            await delayUntilEventIngested(fetchDistinctIdsRows)
            const clickHouseDistinctIds = await hub.db.fetchDistinctIdValues(persons[0], Database.ClickHouse)
            expect(clickHouseDistinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))

            // verify personContainer
            expect(persons[0]).toEqual(await personContainer.get())
        })

        it('merges people when non-anon user identified', async () => {
            await hub.db.createPerson(timestamp, {}, {}, {}, 2, null, false, uuid.toString(), ['old-user'])
            await hub.db.createPerson(timestamp2, {}, {}, {}, 2, null, true, uuid2.toString(), ['new-user'])

            const personContainer = await personState({
                event: '$create_alias',
                distinct_id: 'new-user', // note we merge into this person and that's important
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
            const clickhousePersons = await delayUntilEventIngested(() => fetchPersonsRows(), 2)
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
            await delayUntilEventIngested(fetchDistinctIdsRows)
            const clickHouseDistinctIds = await hub.db.fetchDistinctIdValues(persons[0], Database.ClickHouse)
            expect(clickHouseDistinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))

            // verify personContainer
            expect(persons[0]).toEqual(await personContainer.get())
        })

        it('merges people when anon user identified', async () => {
            // Currently different from identify
            await hub.db.createPerson(timestamp, {}, {}, {}, 2, null, true, uuid.toString(), ['old-user'])
            await hub.db.createPerson(timestamp2, {}, {}, {}, 2, null, false, uuid2.toString(), ['new-user'])

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
            const clickhousePersons = await delayUntilEventIngested(() => fetchPersonsRows(), 2)
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
            await delayUntilEventIngested(fetchDistinctIdsRows)
            const clickHouseDistinctIds = await hub.db.fetchDistinctIdValues(persons[0], Database.ClickHouse)
            expect(clickHouseDistinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))

            // verify personContainer
            expect(persons[0]).toEqual(await personContainer.get())
        })

        it('merges people when both users identified', async () => {
            // Currently different from identify
            await hub.db.createPerson(timestamp, {}, {}, {}, 2, null, true, uuid.toString(), ['old-user'])
            await hub.db.createPerson(timestamp2, {}, {}, {}, 2, null, true, uuid2.toString(), ['new-user'])

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
            const clickhousePersons = await delayUntilEventIngested(() => fetchPersonsRows(), 2)
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
            await delayUntilEventIngested(fetchDistinctIdsRows)
            const clickHouseDistinctIds = await hub.db.fetchDistinctIdValues(persons[0], Database.ClickHouse)
            expect(clickHouseDistinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))

            // verify personContainer
            expect(persons[0]).toEqual(await personContainer.get())
        })
    })

    describe('foreign key updates in other tables', () => {
        test('feature flag hash key overrides with no conflicts', async () => {
            const anonPerson = await hub.db.createPerson(timestamp, {}, {}, {}, 2, null, false, uuid.toString(), [
                'anonymous_id',
            ])
            const identifiedPerson = await hub.db.createPerson(
                timestamp,
                {},
                {},
                {},
                2,
                null,
                false,
                uuid2.toString(),
                ['new_distinct_id']
            )

            // existing overrides
            await insertRow(hub.db.postgres, 'posthog_featureflaghashkeyoverride', {
                team_id: 2,
                person_id: anonPerson.id,
                feature_flag_key: 'beta-feature',
                hash_key: 'example_id',
            })
            await insertRow(hub.db.postgres, 'posthog_featureflaghashkeyoverride', {
                team_id: 2,
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
                [2],
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

        test('feature flag hash key overrides with some conflicts handled gracefully', async () => {
            const anonPerson = await hub.db.createPerson(timestamp, {}, {}, {}, 2, null, false, uuid.toString(), [
                'anonymous_id',
            ])
            const identifiedPerson = await hub.db.createPerson(
                timestamp,
                {},
                {},
                {},
                2,
                null,
                false,
                uuid2.toString(),
                ['new_distinct_id']
            )

            // existing overrides for both anonPerson and identifiedPerson
            // which implies a clash when anonPerson is deleted
            await insertRow(hub.db.postgres, 'posthog_featureflaghashkeyoverride', {
                team_id: 2,
                person_id: anonPerson.id,
                feature_flag_key: 'beta-feature',
                hash_key: 'example_id',
            })
            await insertRow(hub.db.postgres, 'posthog_featureflaghashkeyoverride', {
                team_id: 2,
                person_id: identifiedPerson.id,
                feature_flag_key: 'beta-feature',
                hash_key: 'different_id',
            })
            await insertRow(hub.db.postgres, 'posthog_featureflaghashkeyoverride', {
                team_id: 2,
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
                [2],
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

        test('feature flag hash key overrides with no old overrides but existing new person overrides', async () => {
            await hub.db.createPerson(timestamp, {}, {}, {}, 2, null, false, uuid.toString(), ['anonymous_id'])
            const identifiedPerson = await hub.db.createPerson(
                timestamp,
                {},
                {},
                {},
                2,
                null,
                false,
                uuid2.toString(),
                ['new_distinct_id']
            )

            await insertRow(hub.db.postgres, 'posthog_featureflaghashkeyoverride', {
                team_id: 2,
                person_id: identifiedPerson.id,
                feature_flag_key: 'beta-feature',
                hash_key: 'example_id',
            })
            await insertRow(hub.db.postgres, 'posthog_featureflaghashkeyoverride', {
                team_id: 2,
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
                [2],
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
})
