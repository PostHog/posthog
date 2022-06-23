import { PluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { Hub, Person } from '../../../src/types'
import { createHub } from '../../../src/utils/db/hub'
import { UUIDT } from '../../../src/utils/utils'
import { PersonState } from '../../../src/worker/ingestion/person-state'
import { delayUntilEventIngested, resetTestDatabaseClickhouse } from '../../helpers/clickhouse'
import { resetTestDatabase } from '../../helpers/sql'

jest.mock('../../../src/utils/status')
jest.setTimeout(60000) // 60 sec timeout

const timestamp = DateTime.fromISO('2020-01-01T12:00:05.200Z').toUTC()

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
        return new PersonState(
            fullEvent as any,
            2,
            event.distinct_id!,
            timestamp,
            hub.db,
            hub.statsd,
            hub.personManager,
            person,
            uuid
        )
    }

    async function fetchPersonsRows(options: { final?: boolean } = {}) {
        const query = `SELECT * FROM person ${options.final ? 'FINAL' : ''}`
        return (await hub.db.clickhouseQuery(query)).data
    }

    it('creates person if they are new', async () => {
        const createdPerson = await personState({ event: '$pageview', distinct_id: 'new-user' }).update()

        expect(createdPerson).toEqual(
            expect.objectContaining({
                id: expect.any(Number),
                uuid: uuid.toString(),
                properties: {},
                created_at: timestamp,
                version: 0,
            })
        )

        const clickhousePersons = await delayUntilEventIngested(fetchPersonsRows)
        expect(clickhousePersons.length).toEqual(1)
        expect(clickhousePersons[0]).toEqual(
            expect.objectContaining({
                id: uuid.toString(),
                properties: '{}',
                created_at: '2020-01-01 12:00:05.000',
                version: 0,
            })
        )
        expect(hub.personManager.isNewPerson).toHaveBeenCalledTimes(1)
        expect(hub.db.fetchPerson).toHaveBeenCalledTimes(0)
    })

    it('creates person with properties', async () => {
        const createdPerson = await personState({
            event: '$pageview',
            distinct_id: 'new-user',
            properties: {
                $set_once: { a: 1, b: 2 },
                $set: { b: 3, c: 4 },
            },
        }).update()

        expect(createdPerson).toEqual(
            expect.objectContaining({
                id: expect.any(Number),
                uuid: uuid.toString(),
                properties: { a: 1, b: 3, c: 4 },
                created_at: timestamp,
                version: 0,
            })
        )

        const clickhousePersons = await delayUntilEventIngested(fetchPersonsRows)
        expect(clickhousePersons.length).toEqual(1)
        expect(clickhousePersons[0]).toEqual(
            expect.objectContaining({
                id: uuid.toString(),
                properties: JSON.stringify({ a: 1, b: 3, c: 4 }),
                created_at: '2020-01-01 12:00:05.000',
                version: 0,
            })
        )
        expect(hub.personManager.isNewPerson).toHaveBeenCalledTimes(1)
        expect(hub.db.fetchPerson).toHaveBeenCalledTimes(0)
    })

    it('updates person properties if needed', async () => {
        await hub.db.createPerson(timestamp, { b: 3, c: 4 }, {}, {}, 2, null, false, uuid.toString(), ['new-user'])

        const updatedPerson = await personState({
            event: '$pageview',
            distinct_id: 'new-user',
            properties: {
                $set_once: { c: 3, e: 4 },
                $set: { b: 4 },
            },
        }).update()

        expect(updatedPerson).toEqual(
            expect.objectContaining({
                id: expect.any(Number),
                uuid: uuid.toString(),
                properties: { b: 4, c: 4, e: 4 },
                created_at: timestamp,
                version: 1,
            })
        )

        const clickhousePersons = await delayUntilEventIngested(fetchPersonsRows)
        expect(clickhousePersons.length).toEqual(1)
        expect(clickhousePersons[0]).toEqual(
            expect.objectContaining({
                id: uuid.toString(),
                properties: JSON.stringify({ b: 4, c: 4, e: 4 }),
                created_at: '2020-01-01 12:00:05.000',
                version: 1,
            })
        )
        expect(hub.personManager.isNewPerson).toHaveBeenCalledTimes(1)
        expect(hub.db.fetchPerson).toHaveBeenCalledTimes(1)
    })

    it('updating with cached person data skips checking if person is new', async () => {
        const person = await hub.db.createPerson(timestamp, { b: 3, c: 4 }, {}, {}, 2, null, false, uuid.toString(), [
            'new-user',
        ])

        const updatedPerson = await personState(
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

        expect(updatedPerson).toEqual(
            expect.objectContaining({
                id: expect.any(Number),
                uuid: uuid.toString(),
                properties: { b: 4, c: 4, e: 4 },
                created_at: timestamp,
                version: 1,
            })
        )
        expect(hub.personManager.isNewPerson).toHaveBeenCalledTimes(0)
        expect(hub.db.fetchPerson).toHaveBeenCalledTimes(0)

        await delayUntilEventIngested(fetchPersonsRows)
    })

    it('does not update person if not needed', async () => {
        await hub.db.createPerson(timestamp, { b: 3, c: 4 }, {}, {}, 2, null, false, uuid.toString(), ['new-user'])

        const updatedPerson = await personState({
            event: '$pageview',
            distinct_id: 'new-user',
            properties: {
                $set_once: { c: 3 },
                $set: { b: 3 },
            },
        }).update()

        expect(updatedPerson).toEqual(
            expect.objectContaining({
                id: expect.any(Number),
                uuid: uuid.toString(),
                properties: { b: 3, c: 4 },
                created_at: timestamp,
                version: 0,
            })
        )

        expect(hub.db.fetchPerson).toHaveBeenCalledTimes(1)
        await delayUntilEventIngested(fetchPersonsRows)
    })

    // This is a regression test
    it('creates person on $identify event', async () => {
        const createdPerson = await personState({
            event: '$identify',
            distinct_id: 'new-user',
            properties: {
                $set: { foo: 'bar' },
                $anon_distinct_id: 'old-user',
            },
        }).update()

        expect(createdPerson).toEqual(
            expect.objectContaining({
                id: expect.any(Number),
                uuid: uuid.toString(),
                properties: { foo: 'bar' },
                created_at: timestamp,
                version: 0,
            })
        )
        const clickhousePersons = await delayUntilEventIngested(fetchPersonsRows)
        expect(clickhousePersons.length).toEqual(1)
        expect(clickhousePersons[0]).toEqual(
            expect.objectContaining({
                id: uuid.toString(),
                properties: JSON.stringify({ foo: 'bar' }),
                created_at: '2020-01-01 12:00:05.000',
                version: 0,
            })
        )
        expect(hub.db.fetchPerson).toHaveBeenCalledTimes(2)
        expect(hub.personManager.isNewPerson).toHaveBeenCalledTimes(0)
    })

    it('merges people on $identify event', async () => {
        await hub.db.createPerson(timestamp, { a: 1, b: 2 }, {}, {}, 2, null, false, uuid.toString(), ['old-user'])
        await hub.db.createPerson(timestamp, { b: 3, c: 4 }, {}, {}, 2, null, false, uuid2.toString(), ['new-user'])

        await personState({
            event: '$identify',
            distinct_id: 'new-user',
            properties: {
                $anon_distinct_id: 'old-user',
            },
        }).update()
        await hub.db.kafkaProducer.flush()

        const persons = await hub.db.fetchPersons()
        expect(persons.length).toEqual(1)
        expect(persons[0]).toEqual(
            expect.objectContaining({
                id: expect.any(Number),
                uuid: uuid2.toString(),
                properties: { a: 1, b: 3, c: 4 },
                created_at: timestamp,
                is_identified: true,
                version: 1,
            })
        )
        const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
        expect(distinctIds).toEqual(expect.arrayContaining(['new-user', 'old-user']))

        const clickhousePersons = await delayUntilEventIngested(() => fetchPersonsRows({ final: true }), 2)
        expect(clickhousePersons.length).toEqual(2)
        expect(clickhousePersons).toEqual(
            expect.arrayContaining([
                expect.objectContaining({
                    id: uuid2.toString(),
                    properties: JSON.stringify({ a: 1, b: 3, c: 4 }),
                    is_deleted: 0,
                    created_at: '2020-01-01 12:00:05.000',
                    version: 1,
                }),
                expect.objectContaining({
                    id: uuid.toString(),
                    is_deleted: 1,
                    version: 100,
                }),
            ])
        )

        expect(hub.db.fetchPerson).toHaveBeenCalledTimes(2)
        expect(hub.personManager.isNewPerson).toHaveBeenCalledTimes(0)
    })

    it('adds adds new distinct_id and updates is_identified on $identify event', async () => {
        await hub.db.createPerson(timestamp, {}, {}, {}, 2, null, false, uuid2.toString(), ['new-user'])

        await personState({
            event: '$identify',
            distinct_id: 'new-user',
            properties: {
                $anon_distinct_id: 'old-user',
                $set: { foo: 'bar' },
            },
        }).update()
        await hub.db.kafkaProducer.flush()

        const persons = await hub.db.fetchPersons()
        expect(persons.length).toEqual(1)
        expect(persons[0]).toEqual(
            expect.objectContaining({
                id: expect.any(Number),
                uuid: uuid2.toString(),
                properties: { foo: 'bar' },
                created_at: timestamp,
                is_identified: true,
                version: 1,
            })
        )
        const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
        expect(distinctIds).toEqual(expect.arrayContaining(['new-user', 'old-user']))

        expect(hub.personManager.isNewPerson).toHaveBeenCalledTimes(0)
        expect(hub.db.fetchPerson).toHaveBeenCalledTimes(2)

        await delayUntilEventIngested(fetchPersonsRows)
    })

    it('marks user as is_identified on $identify event', async () => {
        await hub.db.createPerson(timestamp, {}, {}, {}, 2, null, false, uuid2.toString(), ['new-user', 'old-user'])

        await personState({
            event: '$identify',
            distinct_id: 'new-user',
            properties: {
                $anon_distinct_id: 'old-user',
                $set: { foo: 'bar' },
            },
        }).update()
        await hub.db.kafkaProducer.flush()

        const persons = await hub.db.fetchPersons()
        expect(persons.length).toEqual(1)
        expect(persons[0]).toEqual(
            expect.objectContaining({
                id: expect.any(Number),
                uuid: uuid2.toString(),
                properties: { foo: 'bar' },
                created_at: timestamp,
                is_identified: true,
                version: 1,
            })
        )

        expect(hub.personManager.isNewPerson).toHaveBeenCalledTimes(0)
        expect(hub.db.fetchPerson).toHaveBeenCalledTimes(2)

        await delayUntilEventIngested(fetchPersonsRows)
    })

    it('does not update person if user already identified and no properties change on $identify event', async () => {
        await hub.db.createPerson(timestamp, {}, {}, {}, 2, null, true, uuid2.toString(), ['new-user', 'old-user'])

        await personState({
            event: '$identify',
            distinct_id: 'new-user',
            properties: {
                $anon_distinct_id: 'old-user',
            },
        }).update()
        await hub.db.kafkaProducer.flush()

        const persons = await hub.db.fetchPersons()
        expect(persons.length).toEqual(1)
        expect(persons[0]).toEqual(
            expect.objectContaining({
                id: expect.any(Number),
                uuid: uuid2.toString(),
                properties: {},
                created_at: timestamp,
                is_identified: true,
                version: 0,
            })
        )

        await delayUntilEventIngested(fetchPersonsRows)
    })

    it('does not merge already identified users', async () => {
        await hub.db.createPerson(timestamp, { a: 1, b: 2 }, {}, {}, 2, null, true, uuid.toString(), ['old-user'])
        await hub.db.createPerson(timestamp, { b: 3, c: 4, d: 5 }, {}, {}, 2, null, false, uuid2.toString(), [
            'new-user',
        ])

        await personState({
            event: '$identify',
            distinct_id: 'new-user',
            properties: {
                $anon_distinct_id: 'old-user',
            },
        }).update()

        const persons = await hub.db.fetchPersons()
        expect(persons.length).toEqual(2)
        await delayUntilEventIngested(fetchPersonsRows)
    })

    it('merges people on $identify event and updates properties with $set/$set_once', async () => {
        await hub.db.createPerson(timestamp, { a: 1, b: 2 }, {}, {}, 2, null, false, uuid.toString(), ['old-user'])
        await hub.db.createPerson(timestamp, { b: 3, c: 4, d: 5 }, {}, {}, 2, null, false, uuid2.toString(), [
            'new-user',
        ])

        await personState({
            event: '$identify',
            distinct_id: 'new-user',
            properties: {
                $set: { d: 6, e: 7 },
                $set_once: { a: 8, f: 9 },
                $anon_distinct_id: 'old-user',
            },
        }).update()
        await hub.db.kafkaProducer.flush()

        const persons = await hub.db.fetchPersons()
        expect(persons.length).toEqual(1)
        expect(persons[0]).toEqual(
            expect.objectContaining({
                id: expect.any(Number),
                uuid: uuid2.toString(),
                properties: { a: 1, b: 3, c: 4, d: 6, e: 7, f: 9 },
                created_at: timestamp,
                is_identified: true,
                version: 1,
            })
        )
        const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
        expect(distinctIds).toEqual(expect.arrayContaining(['new-user', 'old-user']))

        const clickhousePersons = await delayUntilEventIngested(() => fetchPersonsRows({ final: true }), 2)
        expect(clickhousePersons.length).toEqual(2)
        expect(clickhousePersons).toEqual(
            expect.arrayContaining([
                expect.objectContaining({
                    id: uuid2.toString(),
                    properties: JSON.stringify({ a: 1, b: 3, c: 4, d: 6, e: 7, f: 9 }),
                    is_deleted: 0,
                    created_at: '2020-01-01 12:00:05.000',
                    version: 1,
                }),
                expect.objectContaining({
                    id: uuid.toString(),
                    is_deleted: 1,
                    version: 100,
                }),
            ])
        )

        expect(hub.personManager.isNewPerson).toHaveBeenCalledTimes(0)
        expect(hub.db.fetchPerson).toHaveBeenCalledTimes(2)
    })
})
