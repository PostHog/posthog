import { PluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { waitForExpect } from '../../../functional_tests/expectations'
import { Database, Hub, Person } from '../../../src/types'
import { DependencyUnavailableError } from '../../../src/utils/db/error'
import { createHub } from '../../../src/utils/db/hub'
import { PostgresUse } from '../../../src/utils/db/postgres'
import { defaultRetryConfig } from '../../../src/utils/retries'
import { UUIDT } from '../../../src/utils/utils'
import {
    DeferredPersonOverrideWorker,
    DeferredPersonOverrideWriter,
    FlatPersonOverrideWriter,
    PersonOverrideWriter,
    PersonState,
} from '../../../src/worker/ingestion/person-state'
import { delayUntilEventIngested } from '../../helpers/clickhouse'
import { WaitEvent } from '../../helpers/promises'
import { createOrganization, createTeam, fetchPostgresPersons, insertRow } from '../../helpers/sql'

jest.setTimeout(5000) // 5 sec timeout

const timestamp = DateTime.fromISO('2020-01-01T12:00:05.200Z').toUTC()
const timestamp2 = DateTime.fromISO('2020-02-02T12:00:05.200Z').toUTC()
const timestampch = '2020-01-01 12:00:05.000'

interface PersonOverridesMode {
    supportsSyncTransaction: boolean
    getWriter(hub: Hub): PersonOverrideWriter | DeferredPersonOverrideWriter
    fetchPostgresPersonIdOverrides(
        hub: Hub,
        teamId: number
    ): Promise<Set<{ override_person_id: string; old_person_id: string }>>
}

const PersonOverridesModes: Record<string, PersonOverridesMode | undefined> = {
    disabled: undefined,
    'immediate, with mappings': {
        supportsSyncTransaction: true,
        getWriter: (hub) => new PersonOverrideWriter(hub.db.postgres),
        fetchPostgresPersonIdOverrides: async (hub, teamId) => {
            const writer = new PersonOverrideWriter(hub.db.postgres) // XXX: ideally would reference ``this``, not new instance
            return new Set(
                (await writer.getPersonOverrides(teamId)).map(({ old_person_id, override_person_id }) => ({
                    old_person_id,
                    override_person_id,
                }))
            )
        },
    },
    'deferred, with mappings': {
        supportsSyncTransaction: false,
        getWriter: (hub) => new DeferredPersonOverrideWriter(hub.db.postgres),
        fetchPostgresPersonIdOverrides: async (hub, teamId) => {
            const syncWriter = new PersonOverrideWriter(hub.db.postgres)
            await new DeferredPersonOverrideWorker(
                hub.db.postgres,
                hub.db.kafkaProducer,
                syncWriter
            ).processPendingOverrides()
            return new Set(
                (await syncWriter.getPersonOverrides(teamId)).map(({ old_person_id, override_person_id }) => ({
                    old_person_id,
                    override_person_id,
                }))
            )
        },
    },
    'deferred, without mappings (flat)': {
        supportsSyncTransaction: false,
        getWriter: (hub) => new DeferredPersonOverrideWriter(hub.db.postgres),
        fetchPostgresPersonIdOverrides: async (hub, teamId) => {
            const syncWriter = new FlatPersonOverrideWriter(hub.db.postgres)
            await new DeferredPersonOverrideWorker(
                hub.db.postgres,
                hub.db.kafkaProducer,
                syncWriter
            ).processPendingOverrides()
            return new Set(
                (await syncWriter.getPersonOverrides(teamId)).map(({ old_person_id, override_person_id }) => ({
                    old_person_id,
                    override_person_id,
                }))
            )
        },
    },
}

describe('PersonState.update()', () => {
    let hub: Hub
    let closeHub: () => Promise<void>

    let uuid: UUIDT
    let uuid2: UUIDT
    let teamId: number
    let overridesMode: PersonOverridesMode | undefined
    let organizationId: string

    beforeAll(async () => {
        ;[hub, closeHub] = await createHub({})
        await hub.db.clickhouseQuery('SYSTEM STOP MERGES')

        organizationId = await createOrganization(hub.db.postgres)
    })

    beforeEach(async () => {
        overridesMode = undefined
        uuid = new UUIDT()
        uuid2 = new UUIDT()

        teamId = await createTeam(hub.db.postgres, organizationId)

        jest.spyOn(hub.db, 'fetchPerson')
        jest.spyOn(hub.db, 'updatePersonDeprecated')

        jest.useFakeTimers({ advanceTimers: 50 })
        defaultRetryConfig.RETRY_INTERVAL_DEFAULT = 0
    })

    afterEach(() => {
        jest.clearAllTimers()
    })

    afterAll(async () => {
        await closeHub()
        await hub.db.clickhouseQuery('SYSTEM START MERGES')
    })

    function personState(event: Partial<PluginEvent>, customHub?: Hub, maxMergeAttempts?: number) {
        const fullEvent = {
            team_id: teamId,
            properties: {},
            ...event,
        }

        return new PersonState(
            fullEvent as any,
            teamId,
            event.distinct_id!,
            timestamp,
            customHub ? customHub.db : hub.db,
            overridesMode?.getWriter(customHub ?? hub),
            uuid,
            maxMergeAttempts ?? 3 // the default
        )
    }

    async function fetchPostgresPersonsH() {
        return await fetchPostgresPersons(hub.db, teamId)
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
            const person = await personState({
                event: '$pageview',
                distinct_id: 'new-user',
                uuid: event_uuid,
                // `null_byte` validates that `sanitizeJsonbValue` is working as expected
                properties: { $set: { null_byte: '\u0000' } },
            }).updateProperties()
            await hub.db.kafkaProducer.flush()

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid.toString(),
                    properties: { $creator_event_uuid: event_uuid, null_byte: '\uFFFD' },
                    created_at: timestamp,
                    version: 0,
                    is_identified: false,
                })
            )

            expect(hub.db.fetchPerson).toHaveBeenCalledTimes(1)
            expect(hub.db.updatePersonDeprecated).not.toHaveBeenCalled()

            // verify Postgres persons
            const persons = await fetchPostgresPersonsH()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(person)

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining(['new-user']))
        })

        it('handles person being created in a race condition', async () => {
            await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, uuid.toString(), ['new-user'])

            jest.spyOn(hub.db, 'fetchPerson').mockImplementationOnce(() => {
                return Promise.resolve(undefined)
            })

            const person = await personState({ event: '$pageview', distinct_id: 'new-user' }).handleUpdate()
            await hub.db.kafkaProducer.flush()

            // if creation fails we should return the person that another thread already created
            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid.toString(),
                    properties: {},
                    created_at: timestamp,
                    version: 0,
                    is_identified: false,
                })
            )
            expect(hub.db.updatePersonDeprecated).not.toHaveBeenCalled()
            // verify Postgres persons
            const persons = await fetchPostgresPersonsH()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(person)

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(person)
            expect(distinctIds).toEqual(expect.arrayContaining(['new-user']))
        })

        it('handles person being created in a race condition updates properties if needed', async () => {
            await hub.db.createPerson(timestamp, { b: 3, c: 4 }, {}, {}, teamId, null, false, uuid.toString(), [
                'new-user',
            ])

            jest.spyOn(hub.db, 'fetchPerson').mockImplementationOnce(() => {
                return Promise.resolve(undefined)
            })

            const person = await personState({
                event: '$pageview',
                distinct_id: 'new-user',
                properties: {
                    $set_once: { c: 3, e: 4 },
                    $set: { b: 4 },
                },
            }).handleUpdate()
            await hub.db.kafkaProducer.flush()

            // if creation fails we should return the person that another thread already created
            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid.toString(),
                    properties: { b: 4, c: 4, e: 4 },
                    created_at: timestamp,
                    version: 1,
                    is_identified: false,
                })
            )
            expect(hub.db.updatePersonDeprecated).toHaveBeenCalledTimes(1)
            // verify Postgres persons
            const persons = await fetchPostgresPersonsH()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(person)

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(person)
            expect(distinctIds).toEqual(expect.arrayContaining(['new-user']))
        })

        it('creates person with properties', async () => {
            const person = await personState({
                event: '$pageview',
                distinct_id: 'new-user',
                properties: {
                    $set_once: { a: 1, b: 2 },
                    $set: { b: 3, c: 4 },
                },
            }).updateProperties()
            await hub.db.kafkaProducer.flush()

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid.toString(),
                    properties: { a: 1, b: 3, c: 4 },
                    created_at: timestamp,
                    version: 0,
                    is_identified: false,
                })
            )

            expect(hub.db.fetchPerson).toHaveBeenCalledTimes(1)
            expect(hub.db.updatePersonDeprecated).not.toHaveBeenCalled()

            // verify Postgres persons
            const persons = await fetchPostgresPersonsH()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(person)

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining(['new-user']))
        })
    })

    describe('on person update', () => {
        it('updates person properties', async () => {
            await hub.db.createPerson(
                timestamp,
                { b: 3, c: 4, toString: {} },
                {},
                {},
                teamId,
                null,
                false,
                uuid.toString(),
                ['new-user']
            )

            const person = await personState({
                event: '$pageview',
                distinct_id: 'new-user',
                properties: {
                    $set_once: { c: 3, e: 4 },
                    $set: { b: 4, toString: 1, null_byte: '\u0000' },
                },
            }).updateProperties()
            await hub.db.kafkaProducer.flush()

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid.toString(),
                    // `null_byte` validates that `sanitizeJsonbValue` is working as expected
                    properties: { b: 4, c: 4, e: 4, toString: 1, null_byte: '\uFFFD' },
                    created_at: timestamp,
                    version: 1,
                    is_identified: false,
                })
            )

            expect(hub.db.fetchPerson).toHaveBeenCalledTimes(1)

            // verify Postgres persons
            const persons = await fetchPostgresPersonsH()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(person)
        })

        it('updating with cached person data shortcuts to update directly', async () => {
            const personInitial = await hub.db.createPerson(
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

            const personS = personState({
                event: '$pageview',
                distinct_id: 'new-user',
                properties: {
                    $set_once: { c: 3, e: 4 },
                    $set: { b: 4 },
                },
            })
            jest.spyOn(personS, 'handleIdentifyOrAlias').mockReturnValue(Promise.resolve(personInitial))
            const person = await personS.update()
            await hub.db.kafkaProducer.flush()

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid.toString(),
                    properties: { b: 4, c: 4, e: 4 },
                    created_at: timestamp,
                    version: 1,
                    is_identified: false,
                })
            )

            expect(hub.db.fetchPerson).toHaveBeenCalledTimes(0)

            // verify Postgres persons
            const persons = await fetchPostgresPersonsH()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(person)
        })

        it('does not update person if not needed', async () => {
            await hub.db.createPerson(timestamp, { b: 3, c: 4 }, {}, {}, teamId, null, false, uuid.toString(), [
                'new-user',
            ])

            const person = await personState({
                event: '$pageview',
                distinct_id: 'new-user',
                properties: {
                    $set_once: { c: 3 },
                    $set: { b: 3 },
                },
            }).updateProperties()
            await hub.db.kafkaProducer.flush()

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid.toString(),
                    properties: { b: 3, c: 4 },
                    created_at: timestamp,
                    version: 0,
                    is_identified: false,
                })
            )

            expect(hub.db.fetchPerson).toHaveBeenCalledTimes(1)
            expect(hub.db.updatePersonDeprecated).not.toHaveBeenCalled()

            // verify Postgres persons
            const persons = await fetchPostgresPersonsH()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(person)
        })

        it('marks user as is_identified', async () => {
            await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, uuid.toString(), ['new-user'])
            const personS = personState({
                event: '$pageview',
                distinct_id: 'new-user',
                properties: {},
            })
            personS.updateIsIdentified = true

            const person = await personS.updateProperties()
            await hub.db.kafkaProducer.flush()
            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid.toString(),
                    properties: {},
                    created_at: timestamp,
                    version: 1,
                    is_identified: true,
                })
            )

            expect(hub.db.fetchPerson).toHaveBeenCalledTimes(1)
            expect(hub.db.updatePersonDeprecated).toHaveBeenCalledTimes(1)

            // verify Postgres persons
            const persons = await fetchPostgresPersonsH()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(person)

            // Second call no-update
            personS.updateIsIdentified = true // double just in case
            await personS.updateProperties()
            expect(hub.db.updatePersonDeprecated).toHaveBeenCalledTimes(1)
        })

        it('handles race condition when person provided has been merged', async () => {
            // TODO: we don't handle this currently person having been changed / updated properties can get overridden
            // Pass in a person, but another thread merges it - we shouldn't error in this case, but instead if we couldn't update we should retry?
            const mergeDeletedPerson: Person = {
                created_at: timestamp,
                version: 0,
                id: 0,
                team_id: teamId,
                properties: { a: 5, b: 7 },
                is_user_id: 0,
                is_identified: false,
                uuid: uuid2.toString(),
                properties_last_updated_at: {},
                properties_last_operation: {},
            }
            await hub.db.createPerson(timestamp, { a: 6, c: 8 }, {}, {}, teamId, null, true, uuid.toString(), [
                'new-user',
                'old-user',
            ]) // the merged Person

            const personS = personState({
                event: '$pageview',
                distinct_id: 'new-user',
                properties: { $set: { a: 7, d: 9 } },
            })
            jest.spyOn(personS, 'handleIdentifyOrAlias').mockReturnValue(Promise.resolve(mergeDeletedPerson))

            const person = await personS.update()
            await hub.db.kafkaProducer.flush()

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid.toString(),
                    properties: { a: 7, c: 8, d: 9 },
                    created_at: timestamp,
                    version: 1,
                    is_identified: true,
                })
            )

            expect(hub.db.fetchPerson).toHaveBeenCalledTimes(1)
            expect(hub.db.updatePersonDeprecated).toHaveBeenCalledTimes(2)

            // verify Postgres persons
            const persons = await fetchPostgresPersonsH()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(person)
        })
    })

    describe.each(Object.keys(PersonOverridesModes))('on $identify event', (useOverridesMode) => {
        beforeEach(() => {
            overridesMode = PersonOverridesModes[useOverridesMode] // n.b. mutating outer scope here -- be careful
        })

        describe(`overrides: ${useOverridesMode}`, () => {
            it(`no-op when $anon_distinct_id not passed`, async () => {
                const person = await personState({
                    event: '$identify',
                    distinct_id: 'new-user',
                    properties: {
                        $set: { foo: 'bar' },
                    },
                }).handleIdentifyOrAlias()
                await hub.db.kafkaProducer.flush()

                expect(person).toEqual(undefined)
                const persons = await fetchPostgresPersonsH()
                expect(persons.length).toEqual(0)
            })

            it(`creates person with both distinct_ids and marks user as is_identified when $anon_distinct_id passed`, async () => {
                const person = await personState({
                    event: '$identify',
                    distinct_id: 'new-user',
                    properties: {
                        $set: { foo: 'bar' },
                        $anon_distinct_id: 'old-user',
                    },
                }).handleIdentifyOrAlias()
                await hub.db.kafkaProducer.flush()

                expect(person).toEqual(
                    expect.objectContaining({
                        id: expect.any(Number),
                        uuid: uuid.toString(),
                        properties: { foo: 'bar' },
                        created_at: timestamp,
                        version: 0,
                        is_identified: true,
                    })
                )

                expect(hub.db.updatePersonDeprecated).not.toHaveBeenCalled()

                // verify Postgres persons
                const persons = await fetchPostgresPersonsH()
                expect(persons.length).toEqual(1)
                expect(persons[0]).toEqual(person)

                // verify Postgres distinct_ids
                const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
                expect(distinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))
            })

            it(`marks is_identified to be updated when no changes to distinct_ids but $anon_distinct_id passe`, async () => {
                await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, uuid.toString(), [
                    'new-user',
                    'old-user',
                ])

                const personS = personState({
                    event: '$identify',
                    distinct_id: 'new-user',
                    properties: {
                        $anon_distinct_id: 'old-user',
                    },
                })
                const person = await personS.handleIdentifyOrAlias()
                await hub.db.kafkaProducer.flush()

                expect(person).toEqual(
                    expect.objectContaining({
                        id: expect.any(Number),
                        uuid: uuid.toString(),
                        properties: {},
                        created_at: timestamp,
                        version: 0,
                        is_identified: false,
                    })
                )
                expect(personS.updateIsIdentified).toBeTruthy()

                // verify Postgres persons
                const persons = await fetchPostgresPersonsH()
                expect(persons.length).toEqual(1)
                expect(persons[0]).toEqual(person)
            })

            it(`add distinct id and marks user is_identified when passed $anon_distinct_id person does not exists and distinct_id does`, async () => {
                await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, uuid.toString(), ['new-user'])

                const personS = personState({
                    event: '$identify',
                    distinct_id: 'new-user',
                    properties: {
                        $anon_distinct_id: 'old-user',
                    },
                })
                const person = await personS.handleIdentifyOrAlias()
                await hub.db.kafkaProducer.flush()

                const persons = await fetchPostgresPersonsH()
                expect(person).toEqual(
                    expect.objectContaining({
                        id: expect.any(Number),
                        uuid: uuid.toString(),
                        properties: {},
                        created_at: timestamp,
                        version: 0,
                        is_identified: false,
                    })
                )
                expect(personS.updateIsIdentified).toBeTruthy()

                // verify Postgres persons
                expect(persons.length).toEqual(1)
                expect(persons[0]).toEqual(person)

                // verify Postgres distinct_ids
                const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
                expect(distinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))
            })

            it(`add distinct id and marks user as is_identified when passed $anon_distinct_id person exists and distinct_id does not`, async () => {
                await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, uuid.toString(), ['old-user'])

                const personS = personState({
                    event: '$identify',
                    distinct_id: 'new-user',
                    properties: {
                        $anon_distinct_id: 'old-user',
                    },
                })
                const person = await personS.handleIdentifyOrAlias()
                await hub.db.kafkaProducer.flush()

                const persons = await fetchPostgresPersonsH()

                expect(person).toEqual(
                    expect.objectContaining({
                        id: expect.any(Number),
                        uuid: uuid.toString(),
                        properties: {},
                        created_at: timestamp,
                        version: 0,
                        is_identified: false,
                    })
                )
                expect(personS.updateIsIdentified).toBeTruthy()

                // verify Postgres persons
                expect(persons.length).toEqual(1)
                expect(persons[0]).toEqual(person)

                // verify Postgres distinct_ids
                const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
                expect(distinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))
            })

            it(`merge into distinct_id person and marks user as is_identified when both persons have is_identified false`, async () => {
                await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, uuid.toString(), ['old-user'])
                await hub.db.createPerson(timestamp2, {}, {}, {}, teamId, null, false, uuid2.toString(), ['new-user'])

                const person = await personState({
                    event: '$identify',
                    distinct_id: 'new-user',
                    properties: {
                        $anon_distinct_id: 'old-user',
                    },
                }).handleIdentifyOrAlias()
                await hub.db.kafkaProducer.flush()

                expect(person).toEqual(
                    expect.objectContaining({
                        id: expect.any(Number),
                        uuid: expect.any(String),
                        properties: {},
                        created_at: timestamp,
                        version: 1,
                        is_identified: true,
                    })
                )

                // verify Postgres persons
                const persons = await fetchPostgresPersonsH()
                expect(persons.length).toEqual(1)
                expect(persons[0]).toEqual(person)
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
                expect(new Set(clickhousePersons.map((p) => p.id))).toEqual(
                    new Set([uuid.toString(), uuid2.toString()])
                )

                // verify ClickHouse distinct_ids
                await delayUntilEventIngested(() => fetchDistinctIdsClickhouseVersion1())
                const clickHouseDistinctIds = await fetchDistinctIdsClickhouse(persons[0])
                expect(clickHouseDistinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))
            })

            it(`merge into distinct_id person and marks user as is_identified when distinct_id user is identified and $anon_distinct_id user is not`, async () => {
                await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, uuid.toString(), ['old-user'])
                await hub.db.createPerson(timestamp2, {}, {}, {}, teamId, null, true, uuid2.toString(), ['new-user'])

                const person = await personState({
                    event: '$identify',
                    distinct_id: 'new-user',
                    properties: {
                        $anon_distinct_id: 'old-user',
                    },
                }).handleIdentifyOrAlias()
                await hub.db.kafkaProducer.flush()

                expect(person).toEqual(
                    expect.objectContaining({
                        id: expect.any(Number),
                        uuid: expect.any(String),
                        properties: {},
                        created_at: timestamp,
                        version: 1,
                        is_identified: true,
                    })
                )

                // verify Postgres persons
                const persons = await fetchPostgresPersonsH()
                expect(persons.length).toEqual(1)
                expect(persons[0]).toEqual(person)
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
                expect(new Set(clickhousePersons.map((p) => p.id))).toEqual(
                    new Set([uuid.toString(), uuid2.toString()])
                )

                // verify ClickHouse distinct_ids
                await delayUntilEventIngested(() => fetchDistinctIdsClickhouseVersion1())
                const clickHouseDistinctIds = await fetchDistinctIdsClickhouse(persons[0])
                expect(clickHouseDistinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))
            })

            it(`does not merge people when distinct_id user is not identified and $anon_distinct_id user is`, async () => {
                await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, true, uuid.toString(), ['old-user'])
                await hub.db.createPerson(timestamp2, {}, {}, {}, teamId, null, false, uuid2.toString(), ['new-user'])

                const personS = personState({
                    event: '$identify',
                    distinct_id: 'new-user',
                    properties: {
                        $anon_distinct_id: 'old-user',
                    },
                })
                const person = await personS.handleIdentifyOrAlias()
                await hub.db.kafkaProducer.flush()

                expect(personS.updateIsIdentified).toBeTruthy()
                expect(person).toEqual(
                    expect.objectContaining({
                        id: expect.any(Number),
                        uuid: uuid2.toString(),
                        properties: {},
                        created_at: timestamp2,
                        version: 0,
                        is_identified: false,
                    })
                )

                // verify Postgres persons
                const persons = (await fetchPostgresPersonsH()).sort((a, b) => a.id - b.id)
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
                expect(persons[1]).toEqual(person)

                // verify Postgres distinct_ids
                const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
                expect(distinctIds).toEqual(expect.arrayContaining(['old-user']))
                const distinctIds2 = await hub.db.fetchDistinctIdValues(persons[1])
                expect(distinctIds2).toEqual(expect.arrayContaining(['new-user']))
            })

            it(`does not merge people when both users are identified`, async () => {
                await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, true, uuid.toString(), ['old-user'])
                await hub.db.createPerson(timestamp2, {}, {}, {}, teamId, null, true, uuid2.toString(), ['new-user'])

                const person = await personState({
                    event: '$identify',
                    distinct_id: 'new-user',
                    properties: {
                        $anon_distinct_id: 'old-user',
                    },
                }).handleIdentifyOrAlias()
                await hub.db.kafkaProducer.flush()

                expect(person).toEqual(
                    expect.objectContaining({
                        id: expect.any(Number),
                        uuid: uuid2.toString(),
                        properties: {},
                        created_at: timestamp2,
                        version: 0,
                        is_identified: true,
                    })
                )

                // verify Postgres persons
                const persons = (await fetchPostgresPersonsH()).sort((a, b) => a.id - b.id)
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
                expect(persons[1]).toEqual(person)

                // verify Postgres distinct_ids
                const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
                expect(distinctIds).toEqual(expect.arrayContaining(['old-user']))
                const distinctIds2 = await hub.db.fetchDistinctIdValues(persons[1])
                expect(distinctIds2).toEqual(expect.arrayContaining(['new-user']))
            })

            it(`merge into distinct_id person and updates properties with $set/$set_once`, async () => {
                await hub.db.createPerson(timestamp, { a: 1, b: 2 }, {}, {}, teamId, null, false, uuid.toString(), [
                    'old-user',
                ])
                await hub.db.createPerson(
                    timestamp2,
                    { b: 3, c: 4, d: 5 },
                    {},
                    {},
                    teamId,
                    null,
                    false,
                    uuid2.toString(),
                    ['new-user']
                )

                const person = await personState({
                    event: '$identify',
                    distinct_id: 'new-user',
                    properties: {
                        $set: { d: 6, e: 7 },
                        $set_once: { a: 8, f: 9 },
                        $anon_distinct_id: 'old-user',
                    },
                }).handleIdentifyOrAlias()
                await hub.db.kafkaProducer.flush()

                expect(person).toEqual(
                    expect.objectContaining({
                        id: expect.any(Number),
                        uuid: expect.any(String),
                        properties: { a: 1, b: 3, c: 4, d: 6, e: 7, f: 9 },
                        created_at: timestamp,
                        version: 1,
                        is_identified: true,
                    })
                )

                // verify Postgres persons
                const persons = await fetchPostgresPersonsH()
                expect(persons.length).toEqual(1)
                expect(persons[0]).toEqual(person)
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
                expect(new Set(clickhousePersons.map((p) => p.id))).toEqual(
                    new Set([uuid.toString(), uuid2.toString()])
                )

                // verify ClickHouse distinct_ids
                await delayUntilEventIngested(() => fetchDistinctIdsClickhouseVersion1())
                const clickHouseDistinctIds = await fetchDistinctIdsClickhouse(persons[0])
                expect(clickHouseDistinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))
            })

            it(`handles race condition when other thread creates the user`, async () => {
                await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, uuid.toString(), ['old-user'])

                // Fake the race by assuming createPerson was called before the addDistinctId creation above
                jest.spyOn(hub.db, 'addDistinctId').mockImplementation(async (person, distinctId) => {
                    await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, uuid2.toString(), [
                        distinctId,
                    ])
                    await hub.db.addDistinctId(person, distinctId) // this throws
                })

                const person = await personState({
                    event: '$identify',
                    distinct_id: 'old-user',
                    properties: {
                        $anon_distinct_id: 'new-user',
                    },
                }).handleIdentifyOrAlias()
                await hub.db.kafkaProducer.flush()
                jest.spyOn(hub.db, 'addDistinctId').mockRestore() // Necessary for other tests not to fail

                // if creation fails we should return the person that another thread already created
                expect(person).toEqual(
                    expect.objectContaining({
                        id: expect.any(Number),
                        uuid: uuid.toString(),
                        properties: {},
                        created_at: timestamp,
                        version: 1,
                        is_identified: true,
                    })
                )
                // expect(hub.db.updatePersonDeprecated).not.toHaveBeenCalled()
                // verify Postgres persons
                const persons = await fetchPostgresPersonsH()
                expect(persons.length).toEqual(1)
                expect(persons[0]).toEqual(person)

                // verify Postgres distinct_ids
                const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
                expect(distinctIds).toEqual(expect.arrayContaining(['new-user']))
            })
        })
    })

    describe('on $create_alias events', () => {
        // All the functionality tests are provided above in $identify tests, here we just make sure the calls are equivalent
        it('calls merge on $identify as expected', async () => {
            const state: PersonState = personState(
                {
                    event: '$identify',
                    distinct_id: 'new-user',
                    properties: { $anon_distinct_id: 'old-user' },
                },
                hub
            )
            jest.spyOn(state, 'merge').mockImplementation(() => {
                return Promise.resolve(undefined)
            })
            await state.handleIdentifyOrAlias()
            expect(state.merge).toHaveBeenCalledWith('old-user', 'new-user', teamId, timestamp)
            jest.spyOn(state, 'merge').mockRestore()
        })

        it('calls merge on $create_alias as expected', async () => {
            const state: PersonState = personState(
                {
                    event: '$create_alias',
                    distinct_id: 'new-user',
                    properties: { alias: 'old-user' },
                },
                hub
            )
            jest.spyOn(state, 'merge').mockImplementation(() => {
                return Promise.resolve(undefined)
            })

            await state.handleIdentifyOrAlias()
            expect(state.merge).toHaveBeenCalledWith('old-user', 'new-user', teamId, timestamp)
            jest.spyOn(state, 'merge').mockRestore()
        })

        it('calls merge on $merge_dangerously as expected', async () => {
            const state: PersonState = personState(
                {
                    event: '$merge_dangerously',
                    distinct_id: 'new-user',
                    properties: { alias: 'old-user' },
                },
                hub
            )
            jest.spyOn(state, 'merge').mockImplementation(() => {
                return Promise.resolve(undefined)
            })

            await state.handleIdentifyOrAlias()
            expect(state.merge).toHaveBeenCalledWith('old-user', 'new-user', teamId, timestamp)
            jest.spyOn(state, 'merge').mockRestore()
        })
    })

    describe.each(Object.keys(PersonOverridesModes))('on $merge_dangerously events', (useOverridesMode) => {
        beforeEach(() => {
            overridesMode = PersonOverridesModes[useOverridesMode] // n.b. mutating outer scope here -- be careful
        })

        describe(`overrides: ${useOverridesMode}`, () => {
            // only difference between $merge_dangerously and $identify
            it(`merge_dangerously can merge people when alias id user is identified`, async () => {
                await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, true, uuid.toString(), ['old-user'])
                await hub.db.createPerson(timestamp2, {}, {}, {}, teamId, null, true, uuid2.toString(), ['new-user'])

                const person = await personState({
                    event: '$merge_dangerously',
                    distinct_id: 'new-user',
                    properties: {
                        alias: 'old-user',
                    },
                }).handleIdentifyOrAlias()
                await hub.db.kafkaProducer.flush()

                expect(person).toEqual(
                    expect.objectContaining({
                        id: expect.any(Number),
                        uuid: expect.any(String),
                        properties: {},
                        created_at: timestamp,
                        version: 1,
                        is_identified: true,
                    })
                )

                // verify Postgres persons
                const persons = await fetchPostgresPersonsH()
                expect(persons.length).toEqual(1)
                expect(persons[0]).toEqual(person)
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
                expect(new Set(clickhousePersons.map((p) => p.id))).toEqual(
                    new Set([uuid.toString(), uuid2.toString()])
                )

                // verify ClickHouse distinct_ids
                await delayUntilEventIngested(() => fetchDistinctIdsClickhouseVersion1())
                const clickHouseDistinctIds = await fetchDistinctIdsClickhouse(persons[0])
                expect(clickHouseDistinctIds).toEqual(expect.arrayContaining(['old-user', 'new-user']))
            })
        })
    })

    describe('illegal aliasing', () => {
        const illegalIds = ['', '   ', 'null', 'undefined', '"undefined"', '[object Object]', '"[object Object]"']
        it.each(illegalIds)('stops $identify if current distinct_id is illegal: `%s`', async (illegalId: string) => {
            const person = await personState({
                event: '$identify',
                distinct_id: illegalId,
                properties: {
                    $anon_distinct_id: 'anonymous_id',
                },
            }).handleIdentifyOrAlias()

            expect(person).toEqual(undefined)
            const persons = await fetchPostgresPersonsH()
            expect(persons.length).toEqual(0)
        })

        it.each(illegalIds)('stops $identify if $anon_distinct_id is illegal: `%s`', async (illegalId: string) => {
            const person = await personState({
                event: '$identify',
                distinct_id: 'some_distinct_id',
                properties: {
                    $anon_distinct_id: illegalId,
                },
            }).handleIdentifyOrAlias()

            expect(person).toEqual(undefined)
            const persons = await fetchPostgresPersonsH()
            expect(persons.length).toEqual(0)
        })

        it('stops $create_alias if current distinct_id is illegal', async () => {
            const person = await personState({
                event: '$create_alias',
                distinct_id: 'false',
                properties: {
                    alias: 'some_distinct_id',
                },
            }).handleIdentifyOrAlias()

            expect(person).toEqual(undefined)
            const persons = await fetchPostgresPersonsH()
            expect(persons.length).toEqual(0)
        })

        it('stops $create_alias if alias is illegal', async () => {
            const person = await personState({
                event: '$create_alias',
                distinct_id: 'some_distinct_id',
                properties: {
                    alias: 'null',
                },
            }).handleIdentifyOrAlias()

            expect(person).toEqual(undefined)
            const persons = await fetchPostgresPersonsH()
            expect(persons.length).toEqual(0)
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

            const [person] = await fetchPostgresPersonsH()
            expect([identifiedPerson.id, anonPerson.id]).toContain(person.id)
            expect(await hub.db.fetchDistinctIdValues(person)).toEqual(['anonymous_id', 'new_distinct_id'])
            expect(person.is_identified).toEqual(true)

            const result = await hub.db.postgres.query(
                PostgresUse.COMMON_WRITE,
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

            const [person] = await fetchPostgresPersonsH()
            expect([identifiedPerson.id, anonPerson.id]).toContain(person.id)
            expect(await hub.db.fetchDistinctIdValues(person)).toEqual(['anonymous_id', 'new_distinct_id'])
            expect(person.is_identified).toEqual(true)

            const result = await hub.db.postgres.query(
                PostgresUse.COMMON_WRITE,
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

            const [person] = await fetchPostgresPersonsH()
            expect([identifiedPerson.id, anonPerson.id]).toContain(person.id)
            expect(await hub.db.fetchDistinctIdValues(person)).toEqual(['anonymous_id', 'new_distinct_id'])
            expect(person.is_identified).toEqual(true)

            const result = await hub.db.postgres.query(
                PostgresUse.COMMON_WRITE,
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
    describe.each(Object.keys(PersonOverridesModes))('on persons merges', (useOverridesMode) => {
        // For some reason these tests failed if I ran them with a hub shared
        // with other tests, so I'm creating a new hub for each test.
        let hub: Hub
        let closeHub: () => Promise<void>

        beforeEach(async () => {
            ;[hub, closeHub] = await createHub({})
            overridesMode = PersonOverridesModes[useOverridesMode] // n.b. mutating outer scope here -- be careful

            jest.spyOn(hub.db, 'fetchPerson')
            jest.spyOn(hub.db, 'updatePersonDeprecated')
        })

        afterEach(async () => {
            await closeHub()
        })
        describe(`overrides: ${useOverridesMode}`, () => {
            it(`no-op if persons already merged`, async () => {
                await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, true, uuid.toString(), [
                    'first',
                    'second',
                ])
                const state: PersonState = personState({}, hub)
                jest.spyOn(hub.db.kafkaProducer, 'queueMessages')
                const person = await state.merge('second', 'first', teamId, timestamp)
                await hub.db.kafkaProducer.flush()

                expect(person).toEqual(
                    expect.objectContaining({
                        id: expect.any(Number),
                        uuid: uuid.toString(),
                        properties: {},
                        created_at: timestamp,
                        version: 0,
                        is_identified: true,
                    })
                )
                expect(hub.db.updatePersonDeprecated).not.toHaveBeenCalled()
                expect(hub.db.kafkaProducer.queueMessages).not.toHaveBeenCalled()
            })

            it(`postgres and clickhouse get updated`, async () => {
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

                const state: PersonState = personState({}, hub)
                jest.spyOn(hub.db.kafkaProducer, 'queueMessages')
                const person = await state.mergePeople({
                    mergeInto: first,
                    mergeIntoDistinctId: 'first',
                    otherPerson: second,
                    otherPersonDistinctId: 'second',
                })
                await hub.db.kafkaProducer.flush()

                expect(person).toEqual(
                    expect.objectContaining({
                        id: expect.any(Number),
                        uuid: uuid.toString(),
                        properties: {},
                        created_at: timestamp,
                        version: 1,
                        is_identified: true,
                    })
                )

                expect(hub.db.updatePersonDeprecated).toHaveBeenCalledTimes(1)
                expect(hub.db.kafkaProducer.queueMessages).toHaveBeenCalledTimes(1)
                // verify Postgres persons
                const persons = await fetchPostgresPersonsH()
                expect(persons.length).toEqual(1)
                expect(persons[0]).toEqual(person)

                // verify Postgres distinct_ids
                const distinctIds = await hub.db.fetchDistinctIdValues(person)
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
                const clickHouseDistinctIds = await fetchDistinctIdsClickhouse(person)
                expect(clickHouseDistinctIds).toEqual(expect.arrayContaining(['first', 'second']))

                // verify Postgres person_id overrides, if applicable
                if (overridesMode) {
                    const overrides = await overridesMode.fetchPostgresPersonIdOverrides(hub, teamId)
                    expect(overrides).toEqual(new Set([{ old_person_id: second.uuid, override_person_id: first.uuid }]))
                    // & CH person overrides
                    // TODO
                }
            })

            it(`throws if postgres unavailable`, async () => {
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

                const state: PersonState = personState({}, hub)
                // break postgres
                const error = new DependencyUnavailableError('testing', 'Postgres', new Error('test'))
                jest.spyOn(hub.db.postgres, 'transaction').mockImplementation(() => {
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

                expect(hub.db.postgres.transaction).toHaveBeenCalledTimes(1)
                jest.spyOn(hub.db.postgres, 'transaction').mockRestore()
                expect(hub.db.kafkaProducer.queueMessages).not.toBeCalled()
                // verify Postgres persons
                const persons = await fetchPostgresPersonsH()
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

            it(`retries merges up to retry limit if postgres down`, async () => {
                await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, uuid.toString(), ['first'])
                await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, uuid2.toString(), ['second'])

                const state: PersonState = personState({}, hub)
                // break postgres
                const error = new DependencyUnavailableError('testing', 'Postgres', new Error('test'))
                jest.spyOn(state, 'mergePeople').mockImplementation(() => {
                    throw error
                })
                jest.spyOn(hub.db.kafkaProducer, 'queueMessages')
                await expect(state.merge('second', 'first', teamId, timestamp)).rejects.toThrow(error)

                await hub.db.kafkaProducer.flush()

                expect(state.mergePeople).toHaveBeenCalledTimes(3)
                jest.spyOn(state, 'mergePeople').mockRestore()
                expect(hub.db.kafkaProducer.queueMessages).not.toBeCalled()
                // verify Postgres persons
                const persons = await fetchPostgresPersonsH()
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

            it(`handleIdentifyOrAlias does not throw on merge failure`, async () => {
                // TODO: This the current state, we should probably change it
                await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, uuid.toString(), ['first'])
                await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, uuid2.toString(), ['second'])

                const state: PersonState = personState(
                    { event: '$merge_dangerously', distinct_id: 'first', properties: { alias: 'second' } },
                    hub
                )
                // break postgres
                const error = new DependencyUnavailableError('testing', 'Postgres', new Error('test'))
                jest.spyOn(state, 'mergePeople').mockImplementation(() => {
                    throw error
                })
                jest.spyOn(hub.db.kafkaProducer, 'queueMessages')
                await state.handleIdentifyOrAlias()
                await hub.db.kafkaProducer.flush()

                expect(state.mergePeople).toHaveBeenCalledTimes(3)
                jest.spyOn(state, 'mergePeople').mockRestore()
                expect(hub.db.kafkaProducer.queueMessages).not.toBeCalled()
                // verify Postgres persons
                const persons = await fetchPostgresPersonsH()
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

            it(`does not commit partial transactions on override conflicts`, async () => {
                if (!overridesMode?.supportsSyncTransaction) {
                    return
                }
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

                const state: PersonState = personState({}, hub)
                const originalPostgresQuery = hub.db.postgres.query.bind(hub.db.postgres)
                const error = new Error('Conflict')
                const mockPostgresQuery = jest
                    .spyOn(hub.db.postgres, 'query')
                    .mockImplementation(
                        async (
                            use: PostgresUse,
                            query: any,
                            values: any[] | undefined,
                            tag: string,
                            ...args: any[]
                        ) => {
                            if (tag === 'transitivePersonOverrides') {
                                throw error
                            }
                            return await originalPostgresQuery(use, query, values, tag, ...args)
                        }
                    )

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

                // verify Postgres persons
                const personsAfterFailure = await fetchPostgresPersonsH()
                expect(personsAfterFailure).toEqual(
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

                // verify Postgres distinct_ids
                const distinctIdsAfterFailure = [
                    await hub.db.fetchDistinctIdValues(personsAfterFailure[0]),
                    await hub.db.fetchDistinctIdValues(personsAfterFailure[1]),
                ]
                expect(distinctIdsAfterFailure).toEqual(expect.arrayContaining([['first'], ['second']]))

                // verify Postgres person_id overrides
                const overridesAfterFailure = await overridesMode!.fetchPostgresPersonIdOverrides(hub, teamId)
                expect(overridesAfterFailure).toEqual(new Set())

                // Now verify we successfully get to our target state if we do not have
                // any db errors.
                mockPostgresQuery.mockRestore()
                const person = await state.mergePeople({
                    mergeInto: first,
                    mergeIntoDistinctId: 'first',
                    otherPerson: second,
                    otherPersonDistinctId: 'second',
                })
                await hub.db.kafkaProducer.flush()

                expect(person).toEqual(
                    expect.objectContaining({
                        id: expect.any(Number),
                        uuid: uuid.toString(),
                        properties: {},
                        created_at: timestamp,
                        version: 1,
                        is_identified: true,
                    })
                )

                // verify Postgres persons
                const persons = await fetchPostgresPersonsH()
                expect(persons.length).toEqual(1)
                expect(persons[0]).toEqual(person)

                // verify Postgres distinct_ids
                const distinctIds = await hub.db.fetchDistinctIdValues(person)
                expect(distinctIds).toEqual(expect.arrayContaining(['first', 'second']))

                // verify Postgres person_id overrides
                const overrides = await overridesMode!.fetchPostgresPersonIdOverrides(hub, teamId)
                expect(overrides).toEqual(new Set([{ old_person_id: second.uuid, override_person_id: first.uuid }]))
            })

            it(`handles a chain of overrides being applied concurrently`, async () => {
                const first: Person = await hub.db.createPerson(
                    timestamp,
                    { first: true },
                    {},
                    {},
                    teamId,
                    null,
                    false,
                    uuid.toString(),
                    ['first']
                )
                const second: Person = await hub.db.createPerson(
                    timestamp.plus({ minutes: 2 }),
                    { second: true },
                    {},
                    {},
                    teamId,
                    null,
                    false,
                    uuid2.toString(),
                    ['second']
                )
                const third: Person = await hub.db.createPerson(
                    timestamp.plus({ minutes: 5 }),
                    { third: true },
                    {},
                    {},
                    teamId,
                    null,
                    false,
                    new UUIDT().toString(),
                    ['third']
                )

                // We want to simulate a concurrent update to person_overrides. We do
                // this by first mocking the implementation to block at a certain point
                // in the transaction, then running the update function twice.
                // We then wait for them to block before letting them resume.
                let resumeExecution: (value: unknown) => void

                const postgresTransaction = hub.db.postgres.transaction.bind(hub.db.postgres)
                jest.spyOn(hub.db.postgres, 'transaction').mockImplementation(
                    async (use: PostgresUse, tag: string, transaction: any) => {
                        if (tag === 'mergePeople') {
                            return await postgresTransaction(use, tag, async (client) => {
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
                            return await postgresTransaction(use, tag, transaction)
                        }
                    }
                )

                await Promise.all([
                    personState(
                        {
                            event: '$merge_dangerously',
                            distinct_id: 'first',
                            properties: {
                                alias: 'second',
                            },
                        },
                        hub,
                        0
                    ).handleIdentifyOrAlias(),
                    personState(
                        {
                            event: '$merge_dangerously',
                            distinct_id: 'second',
                            properties: {
                                alias: 'third',
                            },
                        },
                        hub,
                        0
                    ).handleIdentifyOrAlias(),
                ])

                // Note: we can't verify anything here because the concurrency might have enabled both merges to already happen.

                await Promise.all([
                    personState(
                        {
                            event: '$merge_dangerously',
                            distinct_id: 'first',
                            properties: {
                                alias: 'second',
                            },
                        },
                        hub,
                        0
                    ).handleIdentifyOrAlias(),
                    personState(
                        {
                            event: '$merge_dangerously',
                            distinct_id: 'second',
                            properties: {
                                alias: 'third',
                            },
                        },
                        hub,
                        0
                    ).handleIdentifyOrAlias(),
                ])

                // verify Postgres persons
                const persons = await fetchPostgresPersonsH()
                expect(persons.length).toEqual(1)
                expect(persons[0]).toEqual(
                    expect.objectContaining({
                        id: expect.any(Number),
                        uuid: uuid.toString(), // guaranteed to be merged into this based on timestamps
                        // There's a race condition in our code where
                        // if different distinctIDs are used same time,
                        // then pros can be dropped, see https://docs.google.com/presentation/d/1Osz7r8bKkDD5yFzw0cCtsGVf1LTEifXS-dzuwaS8JGY
                        // properties: { first: true, second: true, third: true },
                        created_at: timestamp,
                        version: 1, // the test intends for it to be a chain, so must get v1, we get v2 if second->first and third->first, but we want it to be third->second->first
                        is_identified: true,
                    })
                )

                // verify Postgres distinct_ids
                const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
                expect(distinctIds).toEqual(expect.arrayContaining(['first', 'second', 'third']))

                // verify Postgres person_id overrides, if applicable
                if (overridesMode) {
                    const overrides = await overridesMode.fetchPostgresPersonIdOverrides(hub, teamId)
                    expect(overrides).toEqual(
                        new Set([
                            { old_person_id: second.uuid, override_person_id: first.uuid },
                            { old_person_id: third.uuid, override_person_id: first.uuid },
                        ])
                    )
                }
            })

            it(`handles a chain of overrides being applied out of order`, async () => {
                const first: Person = await hub.db.createPerson(
                    timestamp,
                    { first: true },
                    {},
                    {},
                    teamId,
                    null,
                    false,
                    uuid.toString(),
                    ['first']
                )
                const second: Person = await hub.db.createPerson(
                    timestamp.plus({ minutes: 2 }),
                    { second: true },
                    {},
                    {},
                    teamId,
                    null,
                    false,
                    uuid2.toString(),
                    ['second']
                )
                const third: Person = await hub.db.createPerson(
                    timestamp.plus({ minutes: 5 }),
                    { third: true },
                    {},
                    {},
                    teamId,
                    null,
                    false,
                    new UUIDT().toString(),
                    ['third']
                )

                await personState(
                    {
                        event: '$merge_dangerously',
                        distinct_id: 'second',
                        properties: {
                            alias: 'third',
                        },
                    },
                    hub,
                    0
                ).handleIdentifyOrAlias()

                await personState(
                    {
                        event: '$merge_dangerously',
                        distinct_id: 'first',
                        properties: {
                            alias: 'second',
                        },
                    },
                    hub,
                    0
                ).handleIdentifyOrAlias()

                // verify Postgres persons
                const persons = await fetchPostgresPersonsH()
                expect(persons.length).toEqual(1)
                expect(persons[0]).toEqual(
                    expect.objectContaining({
                        id: expect.any(Number),
                        uuid: uuid.toString(), // guaranteed to be merged into this based on timestamps
                        properties: { first: true, second: true, third: true },
                        created_at: timestamp,
                        version: 1, // the test intends for it to be a chain, so must get v1, we get v2 if second->first and third->first, but we want it to be third->second->first
                        is_identified: true,
                    })
                )

                // verify Postgres distinct_ids
                const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
                expect(distinctIds).toEqual(expect.arrayContaining(['first', 'second', 'third']))

                // verify Postgres person_id overrides, if applicable
                if (overridesMode) {
                    const overrides = await overridesMode.fetchPostgresPersonIdOverrides(hub, teamId)
                    expect(overrides).toEqual(
                        new Set([
                            { old_person_id: second.uuid, override_person_id: first.uuid },
                            { old_person_id: third.uuid, override_person_id: first.uuid },
                        ])
                    )
                }
            })
        })
    })
})

const PersonOverridesWriterMode = {
    mapping: (hub: Hub) => new PersonOverrideWriter(hub.db.postgres),
    flat: (hub: Hub) => new FlatPersonOverrideWriter(hub.db.postgres),
}

describe.each(Object.keys(PersonOverridesWriterMode))('person overrides writer: %s', (mode) => {
    let hub: Hub
    let closeHub: () => Promise<void>

    let organizationId: string
    let teamId: number
    let writer: PersonOverrideWriter | FlatPersonOverrideWriter

    beforeAll(async () => {
        ;[hub, closeHub] = await createHub({})
        organizationId = await createOrganization(hub.db.postgres)
        writer = PersonOverridesWriterMode[mode](hub)
    })

    beforeEach(async () => {
        teamId = await createTeam(hub.db.postgres, organizationId)
    })

    afterAll(async () => {
        await closeHub()
    })

    it('handles direct overrides', async () => {
        const { postgres } = hub.db

        const defaults = {
            team_id: teamId,
            oldest_event: DateTime.fromMillis(0),
        }

        const override = {
            old_person_id: new UUIDT().toString(),
            override_person_id: new UUIDT().toString(),
        }

        await postgres.transaction(PostgresUse.COMMON_WRITE, '', async (tx) => {
            await writer.addPersonOverride(tx, { ...defaults, ...override })
        })

        expect(await writer.getPersonOverrides(teamId)).toEqual([{ ...defaults, ...override }])
    })

    it('handles transitive overrides', async () => {
        const { postgres } = hub.db

        const defaults = {
            team_id: teamId,
            oldest_event: DateTime.fromMillis(0),
        }

        const overrides = [
            {
                old_person_id: new UUIDT().toString(),
                override_person_id: new UUIDT().toString(),
            },
        ]

        overrides.push({
            old_person_id: overrides[0].override_person_id,
            override_person_id: new UUIDT().toString(),
        })

        await postgres.transaction(PostgresUse.COMMON_WRITE, '', async (tx) => {
            for (const override of overrides) {
                await writer.addPersonOverride(tx, { ...defaults, ...override })
            }
        })

        expect(new Set(await writer.getPersonOverrides(teamId))).toEqual(
            new Set(
                overrides.map(({ old_person_id }) => ({
                    old_person_id,
                    override_person_id: overrides.at(-1)!.override_person_id,
                    ...defaults,
                }))
            )
        )
    })
})

describe('deferred person overrides', () => {
    let hub: Hub
    let closeHub: () => Promise<void>

    // not always used, but used more often then not
    let organizationId: string
    let teamId: number

    let writer: DeferredPersonOverrideWriter
    let syncWriter: PersonOverrideWriter
    let worker: DeferredPersonOverrideWorker

    beforeAll(async () => {
        ;[hub, closeHub] = await createHub({})
        organizationId = await createOrganization(hub.db.postgres)
        writer = new DeferredPersonOverrideWriter(hub.db.postgres)
        syncWriter = new PersonOverrideWriter(hub.db.postgres)
        worker = new DeferredPersonOverrideWorker(hub.db.postgres, hub.db.kafkaProducer, syncWriter)
    })

    beforeEach(async () => {
        teamId = await createTeam(hub.db.postgres, organizationId)
        await hub.db.postgres.query(
            PostgresUse.COMMON_WRITE,
            'TRUNCATE TABLE posthog_pendingpersonoverride',
            undefined,
            ''
        )
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    afterAll(async () => {
        await closeHub()
    })

    const getPendingPersonOverrides = async () => {
        const { rows } = await hub.db.postgres.query(
            PostgresUse.COMMON_WRITE,
            `SELECT old_person_id, override_person_id
                FROM posthog_pendingpersonoverride
                WHERE team_id = ${teamId}`,
            undefined,
            ''
        )
        return rows
    }

    it('moves overrides from the pending table to the overrides table', async () => {
        const { postgres } = hub.db

        const override = {
            old_person_id: new UUIDT().toString(),
            override_person_id: new UUIDT().toString(),
        }

        await postgres.transaction(PostgresUse.COMMON_WRITE, '', async (tx) => {
            await writer.addPersonOverride(tx, { team_id: teamId, ...override, oldest_event: DateTime.fromMillis(0) })
        })

        expect(await getPendingPersonOverrides()).toEqual([override])

        expect(await worker.processPendingOverrides()).toEqual(1)

        expect(await getPendingPersonOverrides()).toMatchObject([])

        expect(
            (await syncWriter.getPersonOverrides(teamId)).map(({ old_person_id, override_person_id }) => [
                old_person_id,
                override_person_id,
            ])
        ).toEqual([[override.old_person_id, override.override_person_id]])

        const clickhouseOverrides = await waitForExpect(async () => {
            const { data } = await hub.db.clickhouse.querying(
                `
                SELECT old_person_id, override_person_id
                FROM person_overrides
                WHERE team_id = ${teamId}
                `,
                { dataObjects: true }
            )
            expect(data).toHaveLength(1)
            return data
        })
        expect(clickhouseOverrides).toEqual([override])
    })

    it('rolls back on kafka producer error', async () => {
        const { postgres } = hub.db

        const override = {
            old_person_id: new UUIDT().toString(),
            override_person_id: new UUIDT().toString(),
        }

        await postgres.transaction(PostgresUse.COMMON_WRITE, '', async (tx) => {
            await writer.addPersonOverride(tx, { team_id: teamId, ...override, oldest_event: DateTime.fromMillis(0) })
        })

        expect(await getPendingPersonOverrides()).toEqual([override])

        jest.spyOn(hub.db.kafkaProducer, 'queueMessages').mockImplementation(() => {
            throw new Error('something bad happened')
        })

        await expect(worker.processPendingOverrides()).rejects.toThrow()

        expect(await getPendingPersonOverrides()).toEqual([override])
    })

    it('ensures advisory lock is held before processing', async () => {
        const { postgres } = hub.db

        let acquiredLock: boolean
        const tryLockComplete = new WaitEvent()
        const readyToReleaseLock = new WaitEvent()

        const transactionHolder = postgres
            .transaction(PostgresUse.COMMON_WRITE, '', async (tx) => {
                const { rows } = await postgres.query(
                    tx,
                    `SELECT pg_try_advisory_lock(${worker.lockId}) as acquired, pg_backend_pid()`,
                    undefined,
                    ''
                )
                ;[{ acquired: acquiredLock }] = rows
                tryLockComplete.set()
                await readyToReleaseLock.wait()
            })
            .then(() => {
                acquiredLock = false
            })

        try {
            await tryLockComplete.wait()
            expect(acquiredLock!).toBe(true)
            await expect(worker.processPendingOverrides()).rejects.toThrow(Error('could not acquire lock'))
        } finally {
            readyToReleaseLock.set()
            await transactionHolder
        }

        expect(acquiredLock!).toBe(false)
        await expect(worker.processPendingOverrides()).resolves.toEqual(0)
    })

    it('respects limit if provided', async () => {
        const { postgres } = hub.db

        const overrides = [...Array(3)].map(() => ({
            old_person_id: new UUIDT().toString(),
            override_person_id: new UUIDT().toString(),
        }))

        await postgres.transaction(PostgresUse.COMMON_WRITE, '', async (tx) => {
            await Promise.all(
                overrides.map(
                    async (override) =>
                        await writer.addPersonOverride(tx, {
                            team_id: teamId,
                            ...override,
                            oldest_event: DateTime.fromMillis(0),
                        })
                )
            )
        })

        expect(await getPendingPersonOverrides()).toEqual(overrides)

        expect(await worker.processPendingOverrides(2)).toEqual(2)
        expect(await getPendingPersonOverrides()).toMatchObject(overrides.slice(-1))

        expect(await worker.processPendingOverrides(2)).toEqual(1)
        expect(await getPendingPersonOverrides()).toEqual([])
    })
})
