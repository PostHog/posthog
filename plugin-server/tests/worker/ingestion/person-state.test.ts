import { PluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { Hub } from '../../../src/types'
import { createHub } from '../../../src/utils/db/hub'
import { UUIDT } from '../../../src/utils/utils'
import { PersonState } from '../../../src/worker/ingestion/person-state'
import { delayUntilEventIngested, resetTestDatabaseClickhouse } from '../../helpers/clickhouse'
import { resetTestDatabase } from '../../helpers/sql'

jest.mock('../../../src/utils/status')
jest.setTimeout(60000) // 60 sec timeout

const timestamp = DateTime.fromISO('2020-01-01T12:00:05.200Z').toUTC()
const uuid = new UUIDT()

describe('PersonState.update()', () => {
    let hub: Hub
    let closeHub: () => Promise<void>

    beforeEach(async () => {
        await resetTestDatabase()
        await resetTestDatabaseClickhouse()
        ;[hub, closeHub] = await createHub({})
        // Avoid collapsing merge tree causing race conditions!
        await hub.db.clickhouseQuery('SYSTEM STOP MERGES')
    })

    afterEach(async () => {
        await closeHub()
        await hub.db.clickhouseQuery('SYSTEM START MERGES')
    })

    function personState(event: Partial<PluginEvent>) {
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
            uuid
        )
    }

    async function fetchPersonsRows(options: { final?: boolean } = {}) {
        const query = `SELECT * FROM person ${options.final ? 'FINAL' : ''}`
        return (await hub.db.clickhouseQuery(query)).data
    }

    it('creates person if theyre new', async () => {
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
    })

    // This is a regression test
    it('creates person on $identify event', async () => {
        const createdPerson = await personState({
            event: '$identify',
            distinct_id: 'new-user',
            properties: {
                $set: { foo: 'bar' },
                $anon_distinct_id: 'old-user-id',
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
    })
})
