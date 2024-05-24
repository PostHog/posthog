import { PluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { waitForExpect } from '../../../functional_tests/expectations'
import { Database, Hub, InternalPerson } from '../../../src/types'
import { DependencyUnavailableError } from '../../../src/utils/db/error'
import { createHub } from '../../../src/utils/db/hub'
import { PostgresUse } from '../../../src/utils/db/postgres'
import { defaultRetryConfig } from '../../../src/utils/retries'
import { UUIDT } from '../../../src/utils/utils'
import {
    DeferredPersonOverrideWorker,
    DeferredPersonOverrideWriter,
    FlatPersonOverrideWriter,
    PersonState,
} from '../../../src/worker/ingestion/person-state'
import { uuidFromDistinctId } from '../../../src/worker/ingestion/person-uuid'
import { delayUntilEventIngested } from '../../helpers/clickhouse'
import { WaitEvent } from '../../helpers/promises'
import { createOrganization, createTeam, fetchPostgresPersons, insertRow } from '../../helpers/sql'

jest.setTimeout(5000) // 5 sec timeout

const timestamp = DateTime.fromISO('2020-01-01T12:00:05.200Z').toUTC()
const timestamp2 = DateTime.fromISO('2020-02-02T12:00:05.200Z').toUTC()
const timestampch = '2020-01-01 12:00:05.000'

interface PersonOverridesMode {
    supportsSyncTransaction: boolean
    getWriter(hub: Hub): DeferredPersonOverrideWriter
    fetchPostgresPersonIdOverrides(
        hub: Hub,
        teamId: number
    ): Promise<Set<{ override_person_id: string; old_person_id: string }>>
}

const PersonOverridesModes: Record<string, PersonOverridesMode | undefined> = {
    disabled: undefined,
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

    let teamId: number
    let overridesMode: PersonOverridesMode | undefined
    let organizationId: string

    // Common Distinct IDs (and their deterministic UUIDs) used in tests below.
    const newUserDistinctId = 'new-user'
    let newUserUuid: string
    const oldUserDistinctId = 'old-user'
    let oldUserUuid: string
    const firstUserDistinctId = 'first'
    let firstUserUuid: string
    const secondUserDistinctId = 'second'
    let secondUserUuid: string

    beforeAll(async () => {
        ;[hub, closeHub] = await createHub({})
        await hub.db.clickhouseQuery('SYSTEM STOP MERGES')

        organizationId = await createOrganization(hub.db.postgres)
    })

    beforeEach(async () => {
        overridesMode = undefined

        teamId = await createTeam(hub.db.postgres, organizationId)

        newUserUuid = uuidFromDistinctId(teamId, newUserDistinctId)
        oldUserUuid = uuidFromDistinctId(teamId, oldUserDistinctId)
        firstUserUuid = uuidFromDistinctId(teamId, firstUserDistinctId)
        secondUserUuid = uuidFromDistinctId(teamId, secondUserDistinctId)

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

    function personState(
        event: Partial<PluginEvent>,
        customHub?: Hub,
        processPerson = true,
        lazyPersonCreation = false,
        timestampParam = timestamp
    ) {
        const fullEvent = {
            team_id: teamId,
            properties: {},
            ...event,
        }

        return new PersonState(
            fullEvent as any,
            teamId,
            event.distinct_id!,
            timestampParam,
            processPerson,
            customHub ? customHub.db : hub.db,
            lazyPersonCreation,
            overridesMode?.getWriter(customHub ?? hub)
        )
    }

    async function fetchPostgresPersonsH() {
        return await fetchPostgresPersons(hub.db, teamId)
    }

    async function fetchPersonsRows() {
        const query = `SELECT * FROM person FINAL WHERE team_id = ${teamId} ORDER BY _offset`
        return (await hub.db.clickhouseQuery(query)).data
    }

    async function fetchOverridesForDistinctId(distinctId: string) {
        const query = `SELECT * FROM person_distinct_id_overrides_mv FINAL WHERE team_id = ${teamId} AND distinct_id = '${distinctId}'`
        return (await hub.db.clickhouseQuery(query)).data
    }

    async function fetchPersonsRowsWithVersionHigerEqualThan(version = 1) {
        const query = `SELECT * FROM person FINAL WHERE team_id = ${teamId} AND version >= ${version}`
        return (await hub.db.clickhouseQuery(query)).data
    }

    async function fetchDistinctIdsClickhouse(person: InternalPerson) {
        return hub.db.fetchDistinctIdValues(person, Database.ClickHouse)
    }

    async function fetchDistinctIdsClickhouseVersion1() {
        const query = `SELECT distinct_id FROM person_distinct_id2 FINAL WHERE team_id = ${teamId} AND version = 1`
        return (await hub.db.clickhouseQuery(query)).data
    }

    describe('on person creation', () => {
        it('creates deterministic person uuids that are different between teams', async () => {
            const event_uuid = new UUIDT().toString()
            const primaryTeamId = teamId
            const personPrimaryTeam = await personState({
                event: '$pageview',
                distinct_id: newUserDistinctId,
                uuid: event_uuid,
            }).updateProperties()

            const otherTeamId = await createTeam(hub.db.postgres, organizationId)
            teamId = otherTeamId
            const personOtherTeam = await personState({
                event: '$pageview',
                distinct_id: newUserDistinctId,
                uuid: event_uuid,
            }).updateProperties()

            await hub.db.kafkaProducer.flush()

            expect(personPrimaryTeam.uuid).toEqual(uuidFromDistinctId(primaryTeamId, newUserDistinctId))
            expect(personOtherTeam.uuid).toEqual(uuidFromDistinctId(otherTeamId, newUserDistinctId))
            expect(personPrimaryTeam.uuid).not.toEqual(personOtherTeam.uuid)
        })

        it('returns an ephemeral user object when lazy creation is enabled and $process_person_profile=false', async () => {
            const event_uuid = new UUIDT().toString()

            const hubParam = undefined
            const processPerson = false
            const lazyPersonCreation = true
            const fakePerson = await personState(
                {
                    event: '$pageview',
                    distinct_id: newUserDistinctId,
                    uuid: event_uuid,
                    properties: { $set: { should_be_dropped: 100 } },
                },
                hubParam,
                processPerson,
                lazyPersonCreation
            ).update()
            await hub.db.kafkaProducer.flush()

            expect(fakePerson).toEqual(
                expect.objectContaining({
                    team_id: teamId,
                    uuid: newUserUuid, // deterministic even though no user rows were created
                    properties: {}, // empty even though there was a $set attempted
                    created_at: DateTime.utc(1970, 1, 1, 0, 0, 5), // fake person created_at
                })
            )
            expect(fakePerson.force_upgrade).toBeUndefined()

            // verify there is no Postgres person
            const persons = await fetchPostgresPersonsH()
            expect(persons.length).toEqual(0)

            // verify there are no Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(fakePerson as InternalPerson)
            expect(distinctIds).toEqual(expect.arrayContaining([]))
        })

        it('merging with lazy person creation creates an override and force_upgrade works', async () => {
            await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, oldUserUuid, [oldUserDistinctId])

            const hubParam = undefined
            let processPerson = true
            const lazyPersonCreation = true
            await personState(
                {
                    event: '$identify',
                    distinct_id: newUserDistinctId,
                    properties: {
                        $anon_distinct_id: oldUserDistinctId,
                    },
                },
                hubParam,
                processPerson,
                lazyPersonCreation
            ).update()
            await hub.db.kafkaProducer.flush()

            await delayUntilEventIngested(() => fetchOverridesForDistinctId(newUserDistinctId))
            const chOverrides = await fetchOverridesForDistinctId(newUserDistinctId)
            expect(chOverrides.length).toEqual(1)

            // Override created for Person that never existed in the DB
            expect(chOverrides).toEqual(
                expect.arrayContaining([
                    expect.objectContaining({
                        distinct_id: newUserDistinctId,
                        person_id: oldUserUuid,
                        version: 1,
                    }),
                ])
            )

            // Using the `distinct_id` again with `processPerson=false` results in
            // `force_upgrade=true` and real Person `uuid` and `created_at`
            processPerson = false
            const event_uuid = new UUIDT().toString()
            const timestampParam = timestamp.plus({ minutes: 5 }) // Event needs to happen after Person creation
            const fakePerson = await personState(
                {
                    event: '$pageview',
                    distinct_id: newUserDistinctId,
                    uuid: event_uuid,
                    properties: { $set: { should_be_dropped: 100 } },
                },
                hubParam,
                processPerson,
                lazyPersonCreation,
                timestampParam
            ).update()
            await hub.db.kafkaProducer.flush()

            expect(fakePerson).toEqual(
                expect.objectContaining({
                    team_id: teamId,
                    uuid: oldUserUuid, // *old* user, because it existed before the merge
                    properties: {}, // empty even though there was a $set attempted
                    created_at: timestamp, // *not* the fake person created_at
                    force_upgrade: true,
                })
            )
        })

        it('creates person if they are new', async () => {
            const event_uuid = new UUIDT().toString()
            const person = await personState({
                event: '$pageview',
                distinct_id: newUserDistinctId,
                uuid: event_uuid,
                // `null_byte` validates that `sanitizeJsonbValue` is working as expected
                properties: { $set: { null_byte: '\u0000' } },
            }).updateProperties()
            await hub.db.kafkaProducer.flush()

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: newUserUuid,
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
            expect(distinctIds).toEqual(expect.arrayContaining([newUserDistinctId]))
        })

        it('creates person if they are new and $process_person_profile=false', async () => {
            // Note that eventually $process_person_profile=false will be optimized so that the person is
            // *not* created here.
            const event_uuid = new UUIDT().toString()
            const processPerson = false
            const person = await personState(
                {
                    event: '$pageview',
                    distinct_id: newUserDistinctId,
                    uuid: event_uuid,
                    properties: { $process_person_profile: false, $set: { a: 1 }, $set_once: { b: 2 } },
                },
                hub,
                processPerson
            ).update()
            await hub.db.kafkaProducer.flush()

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: newUserUuid,
                    properties: {},
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
            // For parity with existing functionality, the Person created in the DB actually gets
            // the $creator_event_uuid property. When we stop creating person rows this won't matter.
            expect(persons[0]).toEqual({ ...person, properties: { $creator_event_uuid: event_uuid } })

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining([newUserDistinctId]))
        })

        it('does not attach existing person properties to $process_person_profile=false events', async () => {
            const originalEventUuid = new UUIDT().toString()
            const person = await personState({
                event: '$pageview',
                distinct_id: newUserDistinctId,
                uuid: originalEventUuid,
                properties: { $set: { c: 420 } },
            }).update()
            await hub.db.kafkaProducer.flush()

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: newUserUuid,
                    properties: { $creator_event_uuid: originalEventUuid, c: 420 },
                    created_at: timestamp,
                    version: 0,
                    is_identified: false,
                })
            )

            // verify Postgres persons
            const persons = await fetchPostgresPersonsH()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(person)

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining([newUserDistinctId]))

            // OK, a person now exists with { c: 420 }, let's prove the properties come back out
            // of the DB.
            const personVerifyProps = await personState({
                event: '$pageview',
                distinct_id: newUserDistinctId,
                uuid: new UUIDT().toString(),
                properties: {},
            }).update()
            expect(personVerifyProps.properties).toEqual({ $creator_event_uuid: originalEventUuid, c: 420 })

            // But they don't when $process_person_profile=false
            const processPersonFalseResult = await personState(
                {
                    event: '$pageview',
                    distinct_id: newUserDistinctId,
                    uuid: new UUIDT().toString(),
                    properties: {},
                },
                hub,
                false
            ).update()
            expect(processPersonFalseResult.properties).toEqual({})
        })

        it('handles person being created in a race condition', async () => {
            await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, newUserUuid, [newUserDistinctId])

            jest.spyOn(hub.db, 'fetchPerson').mockImplementationOnce(() => {
                return Promise.resolve(undefined)
            })

            const person = await personState({ event: '$pageview', distinct_id: newUserDistinctId }).handleUpdate()
            await hub.db.kafkaProducer.flush()

            // if creation fails we should return the person that another thread already created
            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: newUserUuid,
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
            expect(distinctIds).toEqual(expect.arrayContaining([newUserDistinctId]))
        })

        it('handles person being created in a race condition updates properties if needed', async () => {
            await hub.db.createPerson(timestamp, { b: 3, c: 4 }, {}, {}, teamId, null, false, newUserUuid, [
                newUserDistinctId,
            ])

            jest.spyOn(hub.db, 'fetchPerson').mockImplementationOnce(() => {
                return Promise.resolve(undefined)
            })

            const person = await personState({
                event: '$pageview',
                distinct_id: newUserDistinctId,
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
                    uuid: newUserUuid,
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
            expect(distinctIds).toEqual(expect.arrayContaining([newUserDistinctId]))
        })

        it('creates person with properties', async () => {
            const person = await personState({
                event: '$pageview',
                distinct_id: newUserDistinctId,
                properties: {
                    $set_once: { a: 1, b: 2 },
                    $set: { b: 3, c: 4 },
                },
            }).updateProperties()
            await hub.db.kafkaProducer.flush()

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: newUserUuid,
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
            expect(distinctIds).toEqual(expect.arrayContaining([newUserDistinctId]))
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
                newUserUuid,
                [newUserDistinctId]
            )

            const person = await personState({
                event: '$pageview',
                distinct_id: newUserDistinctId,
                properties: {
                    $set_once: { c: 3, e: 4 },
                    $set: { b: 4, toString: 1, null_byte: '\u0000' },
                },
            }).updateProperties()
            await hub.db.kafkaProducer.flush()

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: newUserUuid,
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
                newUserUuid,
                [newUserDistinctId]
            )

            const personS = personState({
                event: '$pageview',
                distinct_id: newUserDistinctId,
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
                    uuid: newUserUuid,
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
            await hub.db.createPerson(timestamp, { b: 3, c: 4 }, {}, {}, teamId, null, false, newUserUuid, [
                newUserDistinctId,
            ])

            const person = await personState({
                event: '$pageview',
                distinct_id: newUserDistinctId,
                properties: {
                    $set_once: { c: 3 },
                    $set: { b: 3 },
                },
            }).updateProperties()
            await hub.db.kafkaProducer.flush()

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: newUserUuid,
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
            await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, newUserUuid, [newUserDistinctId])
            const personS = personState({
                event: '$pageview',
                distinct_id: newUserDistinctId,
                properties: {},
            })
            personS.updateIsIdentified = true

            const person = await personS.updateProperties()
            await hub.db.kafkaProducer.flush()
            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: newUserUuid,
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
            const mergeDeletedPerson: InternalPerson = {
                created_at: timestamp,
                version: 0,
                id: 0,
                team_id: teamId,
                properties: { a: 5, b: 7 },
                is_user_id: 0,
                is_identified: false,
                uuid: uuidFromDistinctId(teamId, 'deleted-user'),
                properties_last_updated_at: {},
                properties_last_operation: {},
            }
            await hub.db.createPerson(timestamp, { a: 6, c: 8 }, {}, {}, teamId, null, true, newUserUuid, [
                newUserDistinctId,
                oldUserDistinctId,
            ]) // the merged Person

            const personS = personState({
                event: '$pageview',
                distinct_id: newUserDistinctId,
                properties: { $set: { a: 7, d: 9 } },
            })
            jest.spyOn(personS, 'handleIdentifyOrAlias').mockReturnValue(Promise.resolve(mergeDeletedPerson))

            const person = await personS.update()
            await hub.db.kafkaProducer.flush()

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: newUserUuid,
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

    describe('on $identify event', () => {
        it(`no-op when $anon_distinct_id not passed`, async () => {
            const person = await personState({
                event: '$identify',
                distinct_id: newUserDistinctId,
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
                distinct_id: newUserDistinctId,
                properties: {
                    $set: { foo: 'bar' },
                    $anon_distinct_id: oldUserDistinctId,
                },
            }).handleIdentifyOrAlias()
            await hub.db.kafkaProducer.flush()

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: newUserUuid,
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
            expect(distinctIds).toEqual(expect.arrayContaining([oldUserDistinctId, newUserDistinctId]))
        })

        it(`marks is_identified to be updated when no changes to distinct_ids but $anon_distinct_id passe`, async () => {
            await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, newUserUuid, [
                newUserDistinctId,
                oldUserDistinctId,
            ])

            const personS = personState({
                event: '$identify',
                distinct_id: newUserDistinctId,
                properties: {
                    $anon_distinct_id: oldUserDistinctId,
                },
            })
            const person = await personS.handleIdentifyOrAlias()
            await hub.db.kafkaProducer.flush()

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: newUserUuid,
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
            await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, newUserUuid, [newUserDistinctId])

            const personS = personState({
                event: '$identify',
                distinct_id: newUserDistinctId,
                properties: {
                    $anon_distinct_id: oldUserDistinctId,
                },
            })
            const person = await personS.handleIdentifyOrAlias()
            await hub.db.kafkaProducer.flush()

            const persons = await fetchPostgresPersonsH()
            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: newUserUuid,
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
            expect(distinctIds).toEqual(expect.arrayContaining([oldUserDistinctId, newUserDistinctId]))
        })

        it(`add distinct id and marks user as is_identified when passed $anon_distinct_id person exists and distinct_id does not`, async () => {
            await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, oldUserUuid, [oldUserDistinctId])

            const personS = personState({
                event: '$identify',
                distinct_id: newUserDistinctId,
                properties: {
                    $anon_distinct_id: oldUserDistinctId,
                },
            })
            const person = await personS.handleIdentifyOrAlias()
            await hub.db.kafkaProducer.flush()

            const persons = await fetchPostgresPersonsH()

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: oldUserUuid,
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
            expect(distinctIds).toEqual(expect.arrayContaining([oldUserDistinctId, newUserDistinctId]))
        })

        it(`merge into distinct_id person and marks user as is_identified when both persons have is_identified false`, async () => {
            await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, oldUserUuid, [oldUserDistinctId])
            await hub.db.createPerson(timestamp2, {}, {}, {}, teamId, null, false, newUserUuid, [newUserDistinctId])

            const person = await personState({
                event: '$identify',
                distinct_id: newUserDistinctId,
                properties: {
                    $anon_distinct_id: oldUserDistinctId,
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
            expect([newUserUuid, oldUserUuid]).toContain(persons[0].uuid)

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining([oldUserDistinctId, newUserDistinctId]))

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
            expect(new Set(clickhousePersons.map((p) => p.id))).toEqual(new Set([newUserUuid, oldUserUuid]))

            // verify ClickHouse distinct_ids
            await delayUntilEventIngested(() => fetchDistinctIdsClickhouseVersion1())
            const clickHouseDistinctIds = await fetchDistinctIdsClickhouse(persons[0])
            expect(clickHouseDistinctIds).toEqual(expect.arrayContaining([oldUserDistinctId, newUserDistinctId]))
        })

        it(`merge into distinct_id person and marks user as is_identified when distinct_id user is identified and $anon_distinct_id user is not`, async () => {
            await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, oldUserUuid, [oldUserDistinctId])
            await hub.db.createPerson(timestamp2, {}, {}, {}, teamId, null, true, newUserUuid, [newUserDistinctId])

            const person = await personState({
                event: '$identify',
                distinct_id: newUserDistinctId,
                properties: {
                    $anon_distinct_id: oldUserDistinctId,
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
            expect([newUserUuid, oldUserUuid]).toContain(persons[0].uuid)

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining([oldUserDistinctId, newUserDistinctId]))

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
            expect(new Set(clickhousePersons.map((p) => p.id))).toEqual(new Set([newUserUuid, oldUserUuid]))

            // verify ClickHouse distinct_ids
            await delayUntilEventIngested(() => fetchDistinctIdsClickhouseVersion1())
            const clickHouseDistinctIds = await fetchDistinctIdsClickhouse(persons[0])
            expect(clickHouseDistinctIds).toEqual(expect.arrayContaining([oldUserDistinctId, newUserDistinctId]))
        })

        it(`does not merge people when distinct_id user is not identified and $anon_distinct_id user is`, async () => {
            await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, true, oldUserUuid, [oldUserDistinctId])
            await hub.db.createPerson(timestamp2, {}, {}, {}, teamId, null, false, newUserUuid, [newUserDistinctId])

            const personS = personState({
                event: '$identify',
                distinct_id: newUserDistinctId,
                properties: {
                    $anon_distinct_id: oldUserDistinctId,
                },
            })
            const person = await personS.handleIdentifyOrAlias()
            await hub.db.kafkaProducer.flush()

            expect(personS.updateIsIdentified).toBeTruthy()
            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: newUserUuid,
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
                    uuid: oldUserUuid,
                    properties: {},
                    created_at: timestamp,
                    version: 0,
                    is_identified: true,
                })
            )
            expect(persons[1]).toEqual(person)

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining([oldUserDistinctId]))
            const distinctIds2 = await hub.db.fetchDistinctIdValues(persons[1])
            expect(distinctIds2).toEqual(expect.arrayContaining([newUserDistinctId]))
        })

        it(`does not merge people when both users are identified`, async () => {
            await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, true, oldUserUuid, [oldUserDistinctId])
            await hub.db.createPerson(timestamp2, {}, {}, {}, teamId, null, true, newUserUuid, [newUserDistinctId])

            const person = await personState({
                event: '$identify',
                distinct_id: newUserDistinctId,
                properties: {
                    $anon_distinct_id: oldUserDistinctId,
                },
            }).handleIdentifyOrAlias()
            await hub.db.kafkaProducer.flush()

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: newUserUuid,
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
                    uuid: oldUserUuid,
                    properties: {},
                    created_at: timestamp,
                    version: 0,
                    is_identified: true,
                })
            )
            expect(persons[1]).toEqual(person)

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining([oldUserDistinctId]))
            const distinctIds2 = await hub.db.fetchDistinctIdValues(persons[1])
            expect(distinctIds2).toEqual(expect.arrayContaining([newUserDistinctId]))
        })

        it(`merge into distinct_id person and updates properties with $set/$set_once`, async () => {
            await hub.db.createPerson(timestamp, { a: 1, b: 2 }, {}, {}, teamId, null, false, oldUserUuid, [
                oldUserDistinctId,
            ])
            await hub.db.createPerson(timestamp2, { b: 3, c: 4, d: 5 }, {}, {}, teamId, null, false, newUserUuid, [
                newUserDistinctId,
            ])

            const person = await personState({
                event: '$identify',
                distinct_id: newUserDistinctId,
                properties: {
                    $set: { d: 6, e: 7 },
                    $set_once: { a: 8, f: 9 },
                    $anon_distinct_id: oldUserDistinctId,
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
            expect([newUserUuid, oldUserUuid]).toContain(persons[0].uuid)

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining([oldUserDistinctId, newUserDistinctId]))

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
            expect(new Set(clickhousePersons.map((p) => p.id))).toEqual(new Set([newUserUuid, oldUserUuid]))

            // verify ClickHouse distinct_ids
            await delayUntilEventIngested(() => fetchDistinctIdsClickhouseVersion1())
            const clickHouseDistinctIds = await fetchDistinctIdsClickhouse(persons[0])
            expect(clickHouseDistinctIds).toEqual(expect.arrayContaining([oldUserDistinctId, newUserDistinctId]))
        })

        it(`handles race condition when other thread creates the user`, async () => {
            await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, oldUserUuid, [oldUserDistinctId])

            // Fake the race by assuming createPerson was called before the addDistinctId creation above
            jest.spyOn(hub.db, 'addDistinctId').mockImplementation(async (person, distinctId) => {
                await hub.db.createPerson(
                    timestamp,
                    {},
                    {},
                    {},
                    teamId,
                    null,
                    false,
                    uuidFromDistinctId(teamId, distinctId),
                    [distinctId]
                )
                await hub.db.addDistinctId(person, distinctId, 0) // this throws
            })

            const person = await personState({
                event: '$identify',
                distinct_id: oldUserDistinctId,
                properties: {
                    $anon_distinct_id: newUserDistinctId,
                },
            }).handleIdentifyOrAlias()
            await hub.db.kafkaProducer.flush()
            jest.spyOn(hub.db, 'addDistinctId').mockRestore() // Necessary for other tests not to fail

            // if creation fails we should return the person that another thread already created
            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: oldUserUuid,
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
            expect(distinctIds).toEqual(expect.arrayContaining([newUserDistinctId]))
        })
    })

    describe('on $create_alias events', () => {
        // All the functionality tests are provided above in $identify tests, here we just make sure the calls are equivalent
        it('calls merge on $identify as expected', async () => {
            const state: PersonState = personState(
                {
                    event: '$identify',
                    distinct_id: newUserDistinctId,
                    properties: { $anon_distinct_id: oldUserDistinctId },
                },
                hub
            )
            jest.spyOn(state, 'merge').mockImplementation(() => {
                return Promise.resolve(undefined)
            })
            await state.handleIdentifyOrAlias()
            expect(state.merge).toHaveBeenCalledWith(oldUserDistinctId, newUserDistinctId, teamId, timestamp)
            jest.spyOn(state, 'merge').mockRestore()
        })

        it('calls merge on $create_alias as expected', async () => {
            const state: PersonState = personState(
                {
                    event: '$create_alias',
                    distinct_id: newUserDistinctId,
                    properties: { alias: oldUserDistinctId },
                },
                hub
            )
            jest.spyOn(state, 'merge').mockImplementation(() => {
                return Promise.resolve(undefined)
            })

            await state.handleIdentifyOrAlias()
            expect(state.merge).toHaveBeenCalledWith(oldUserDistinctId, newUserDistinctId, teamId, timestamp)
            jest.spyOn(state, 'merge').mockRestore()
        })

        it('calls merge on $merge_dangerously as expected', async () => {
            const state: PersonState = personState(
                {
                    event: '$merge_dangerously',
                    distinct_id: newUserDistinctId,
                    properties: { alias: oldUserDistinctId },
                },
                hub
            )
            jest.spyOn(state, 'merge').mockImplementation(() => {
                return Promise.resolve(undefined)
            })

            await state.handleIdentifyOrAlias()
            expect(state.merge).toHaveBeenCalledWith(oldUserDistinctId, newUserDistinctId, teamId, timestamp)
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
                await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, true, oldUserUuid, [oldUserDistinctId])
                await hub.db.createPerson(timestamp2, {}, {}, {}, teamId, null, true, newUserUuid, [newUserDistinctId])

                const person = await personState({
                    event: '$merge_dangerously',
                    distinct_id: newUserDistinctId,
                    properties: {
                        alias: oldUserDistinctId,
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
                expect([newUserUuid, oldUserUuid]).toContain(persons[0].uuid)

                // verify Postgres distinct_ids
                const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
                expect(distinctIds).toEqual(expect.arrayContaining([oldUserDistinctId, newUserDistinctId]))

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
                expect(new Set(clickhousePersons.map((p) => p.id))).toEqual(new Set([newUserUuid, oldUserUuid]))

                // verify ClickHouse distinct_ids
                await delayUntilEventIngested(() => fetchDistinctIdsClickhouseVersion1())
                const clickHouseDistinctIds = await fetchDistinctIdsClickhouse(persons[0])
                expect(clickHouseDistinctIds).toEqual(expect.arrayContaining([oldUserDistinctId, newUserDistinctId]))
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
                uuidFromDistinctId(teamId, 'anonymous_id'),
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
                uuidFromDistinctId(teamId, 'new_distinct_id'),
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
                uuidFromDistinctId(teamId, 'anonymous_id'),
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
                uuidFromDistinctId(teamId, 'new_distinct_id'),
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
                uuidFromDistinctId(teamId, 'anonymous_id'),
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
                uuidFromDistinctId(teamId, 'new_distinct_id'),
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
                await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, true, firstUserUuid, [
                    firstUserDistinctId,
                    secondUserDistinctId,
                ])
                const state: PersonState = personState({}, hub)
                jest.spyOn(hub.db.kafkaProducer, 'queueMessages')
                const person = await state.merge(secondUserDistinctId, firstUserDistinctId, teamId, timestamp)
                await hub.db.kafkaProducer.flush()

                expect(person).toEqual(
                    expect.objectContaining({
                        id: expect.any(Number),
                        uuid: firstUserUuid,
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
                const first: InternalPerson = await hub.db.createPerson(
                    timestamp,
                    {},
                    {},
                    {},
                    teamId,
                    null,
                    false,
                    firstUserUuid,
                    [firstUserDistinctId]
                )
                const second: InternalPerson = await hub.db.createPerson(
                    timestamp,
                    {},
                    {},
                    {},
                    teamId,
                    null,
                    false,
                    secondUserUuid,
                    [secondUserDistinctId]
                )

                const state: PersonState = personState({}, hub)
                jest.spyOn(hub.db.kafkaProducer, 'queueMessages')
                const person = await state.mergePeople({
                    mergeInto: first,
                    mergeIntoDistinctId: firstUserDistinctId,
                    otherPerson: second,
                    otherPersonDistinctId: secondUserDistinctId,
                })
                await hub.db.kafkaProducer.flush()

                expect(person).toEqual(
                    expect.objectContaining({
                        id: expect.any(Number),
                        uuid: firstUserUuid,
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
                expect(distinctIds).toEqual(expect.arrayContaining([firstUserDistinctId, secondUserDistinctId]))

                // verify ClickHouse persons
                await delayUntilEventIngested(() => fetchPersonsRowsWithVersionHigerEqualThan(), 2) // wait until merge and delete processed
                const clickhousePersons = await fetchPersonsRows() // but verify full state
                expect(clickhousePersons).toEqual(
                    expect.arrayContaining([
                        expect.objectContaining({
                            id: firstUserUuid,
                            properties: '{}',
                            created_at: timestampch,
                            version: 1,
                            is_identified: 1,
                        }),
                        expect.objectContaining({
                            id: secondUserUuid,
                            is_deleted: 1,
                            version: 100,
                        }),
                    ])
                )

                // verify ClickHouse distinct_ids
                await delayUntilEventIngested(() => fetchDistinctIdsClickhouseVersion1())
                const clickHouseDistinctIds = await fetchDistinctIdsClickhouse(person)
                expect(clickHouseDistinctIds).toEqual(
                    expect.arrayContaining([firstUserDistinctId, secondUserDistinctId])
                )

                // verify Postgres person_id overrides, if applicable
                if (overridesMode) {
                    const overrides = await overridesMode.fetchPostgresPersonIdOverrides(hub, teamId)
                    expect(overrides).toEqual(new Set([{ old_person_id: second.uuid, override_person_id: first.uuid }]))
                    // & CH person overrides
                    // TODO
                }
            })

            it(`throws if postgres unavailable`, async () => {
                const first: InternalPerson = await hub.db.createPerson(
                    timestamp,
                    {},
                    {},
                    {},
                    teamId,
                    null,
                    false,
                    firstUserUuid,
                    [firstUserDistinctId]
                )
                const second: InternalPerson = await hub.db.createPerson(
                    timestamp,
                    {},
                    {},
                    {},
                    teamId,
                    null,
                    false,
                    secondUserUuid,
                    [secondUserDistinctId]
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
                        mergeIntoDistinctId: firstUserDistinctId,
                        otherPerson: second,
                        otherPersonDistinctId: secondUserDistinctId,
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
                            uuid: firstUserUuid,
                            properties: {},
                            created_at: timestamp,
                            version: 0,
                            is_identified: false,
                        }),
                        expect.objectContaining({
                            id: expect.any(Number),
                            uuid: secondUserUuid,
                            properties: {},
                            created_at: timestamp,
                            version: 0,
                            is_identified: false,
                        }),
                    ])
                )
            })

            it(`retries merges up to retry limit if postgres down`, async () => {
                await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, firstUserUuid, [
                    firstUserDistinctId,
                ])
                await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, secondUserUuid, [
                    secondUserDistinctId,
                ])

                const state: PersonState = personState({}, hub)
                // break postgres
                const error = new DependencyUnavailableError('testing', 'Postgres', new Error('test'))
                jest.spyOn(state, 'mergePeople').mockImplementation(() => {
                    throw error
                })
                jest.spyOn(hub.db.kafkaProducer, 'queueMessages')
                await expect(state.merge(secondUserDistinctId, firstUserDistinctId, teamId, timestamp)).rejects.toThrow(
                    error
                )

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
                            uuid: firstUserUuid,
                            properties: {},
                            created_at: timestamp,
                            version: 0,
                            is_identified: false,
                        }),
                        expect.objectContaining({
                            id: expect.any(Number),
                            uuid: secondUserUuid,
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
                await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, firstUserUuid, [
                    firstUserDistinctId,
                ])
                await hub.db.createPerson(timestamp, {}, {}, {}, teamId, null, false, secondUserUuid, [
                    secondUserDistinctId,
                ])

                const state: PersonState = personState(
                    {
                        event: '$merge_dangerously',
                        distinct_id: firstUserDistinctId,
                        properties: { alias: secondUserDistinctId },
                    },
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
                            uuid: firstUserUuid,
                            properties: {},
                            created_at: timestamp,
                            version: 0,
                            is_identified: false,
                        }),
                        expect.objectContaining({
                            id: expect.any(Number),
                            uuid: secondUserUuid,
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
                const first: InternalPerson = await hub.db.createPerson(
                    timestamp,
                    {},
                    {},
                    {},
                    teamId,
                    null,
                    false,
                    firstUserUuid,
                    [firstUserDistinctId]
                )
                const second: InternalPerson = await hub.db.createPerson(
                    timestamp,
                    {},
                    {},
                    {},
                    teamId,
                    null,
                    false,
                    secondUserUuid,
                    [secondUserDistinctId]
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
                        mergeIntoDistinctId: firstUserDistinctId,
                        otherPerson: second,
                        otherPersonDistinctId: secondUserDistinctId,
                    })
                ).rejects.toThrow(error)
                await hub.db.kafkaProducer.flush()

                // verify Postgres persons
                const personsAfterFailure = await fetchPostgresPersonsH()
                expect(personsAfterFailure).toEqual(
                    expect.arrayContaining([
                        expect.objectContaining({
                            id: expect.any(Number),
                            uuid: firstUserUuid,
                            properties: {},
                            created_at: timestamp,
                            version: 0,
                            is_identified: false,
                        }),
                        expect.objectContaining({
                            id: expect.any(Number),
                            uuid: secondUserUuid,
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
                expect(distinctIdsAfterFailure).toEqual(
                    expect.arrayContaining([[firstUserDistinctId], [secondUserDistinctId]])
                )

                // verify Postgres person_id overrides
                const overridesAfterFailure = await overridesMode!.fetchPostgresPersonIdOverrides(hub, teamId)
                expect(overridesAfterFailure).toEqual(new Set())

                // Now verify we successfully get to our target state if we do not have
                // any db errors.
                mockPostgresQuery.mockRestore()
                const person = await state.mergePeople({
                    mergeInto: first,
                    mergeIntoDistinctId: firstUserDistinctId,
                    otherPerson: second,
                    otherPersonDistinctId: secondUserDistinctId,
                })
                await hub.db.kafkaProducer.flush()

                expect(person).toEqual(
                    expect.objectContaining({
                        id: expect.any(Number),
                        uuid: firstUserUuid,
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
                expect(distinctIds).toEqual(expect.arrayContaining([firstUserDistinctId, secondUserDistinctId]))

                // verify Postgres person_id overrides
                const overrides = await overridesMode!.fetchPostgresPersonIdOverrides(hub, teamId)
                expect(overrides).toEqual(new Set([{ old_person_id: second.uuid, override_person_id: first.uuid }]))
            })

            it(`handles a chain of overrides being applied concurrently`, async () => {
                const first: InternalPerson = await hub.db.createPerson(
                    timestamp,
                    { first: true },
                    {},
                    {},
                    teamId,
                    null,
                    false,
                    firstUserUuid,
                    [firstUserDistinctId]
                )
                const second: InternalPerson = await hub.db.createPerson(
                    timestamp.plus({ minutes: 2 }),
                    { second: true },
                    {},
                    {},
                    teamId,
                    null,
                    false,
                    secondUserUuid,
                    [secondUserDistinctId]
                )
                const third: InternalPerson = await hub.db.createPerson(
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
                            distinct_id: firstUserDistinctId,
                            properties: {
                                alias: secondUserDistinctId,
                            },
                        },
                        hub
                    ).handleIdentifyOrAlias(),
                    personState(
                        {
                            event: '$merge_dangerously',
                            distinct_id: secondUserDistinctId,
                            properties: {
                                alias: 'third',
                            },
                        },
                        hub
                    ).handleIdentifyOrAlias(),
                ])

                // Note: we can't verify anything here because the concurrency might have enabled both merges to already happen.

                await Promise.all([
                    personState(
                        {
                            event: '$merge_dangerously',
                            distinct_id: firstUserDistinctId,
                            properties: {
                                alias: secondUserDistinctId,
                            },
                        },
                        hub
                    ).handleIdentifyOrAlias(),
                    personState(
                        {
                            event: '$merge_dangerously',
                            distinct_id: secondUserDistinctId,
                            properties: {
                                alias: 'third',
                            },
                        },
                        hub
                    ).handleIdentifyOrAlias(),
                ])

                // verify Postgres persons
                const persons = await fetchPostgresPersonsH()
                expect(persons.length).toEqual(1)
                expect(persons[0]).toEqual(
                    expect.objectContaining({
                        id: expect.any(Number),
                        uuid: firstUserUuid, // guaranteed to be merged into this based on timestamps
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
                expect(distinctIds).toEqual(
                    expect.arrayContaining([firstUserDistinctId, secondUserDistinctId, 'third'])
                )

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
                const first: InternalPerson = await hub.db.createPerson(
                    timestamp,
                    { first: true },
                    {},
                    {},
                    teamId,
                    null,
                    false,
                    firstUserUuid,
                    [firstUserDistinctId]
                )
                const second: InternalPerson = await hub.db.createPerson(
                    timestamp.plus({ minutes: 2 }),
                    { second: true },
                    {},
                    {},
                    teamId,
                    null,
                    false,
                    secondUserUuid,
                    [secondUserDistinctId]
                )
                const third: InternalPerson = await hub.db.createPerson(
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
                        distinct_id: secondUserDistinctId,
                        properties: {
                            alias: 'third',
                        },
                    },
                    hub
                ).handleIdentifyOrAlias()

                await personState(
                    {
                        event: '$merge_dangerously',
                        distinct_id: firstUserDistinctId,
                        properties: {
                            alias: secondUserDistinctId,
                        },
                    },
                    hub
                ).handleIdentifyOrAlias()

                // verify Postgres persons
                const persons = await fetchPostgresPersonsH()
                expect(persons.length).toEqual(1)
                expect(persons[0]).toEqual(
                    expect.objectContaining({
                        id: expect.any(Number),
                        uuid: firstUserUuid, // guaranteed to be merged into this based on timestamps
                        properties: { first: true, second: true, third: true },
                        created_at: timestamp,
                        version: 1, // the test intends for it to be a chain, so must get v1, we get v2 if second->first and third->first, but we want it to be third->second->first
                        is_identified: true,
                    })
                )

                // verify Postgres distinct_ids
                const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
                expect(distinctIds).toEqual(
                    expect.arrayContaining([firstUserDistinctId, secondUserDistinctId, 'third'])
                )

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

describe('flat person overrides writer', () => {
    let hub: Hub
    let closeHub: () => Promise<void>

    let organizationId: string
    let teamId: number
    let writer: FlatPersonOverrideWriter

    beforeAll(async () => {
        ;[hub, closeHub] = await createHub({})
        organizationId = await createOrganization(hub.db.postgres)
        writer = new FlatPersonOverrideWriter(hub.db.postgres)
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
    let syncWriter: FlatPersonOverrideWriter
    let worker: DeferredPersonOverrideWorker

    beforeAll(async () => {
        ;[hub, closeHub] = await createHub({})
        organizationId = await createOrganization(hub.db.postgres)
        writer = new DeferredPersonOverrideWriter(hub.db.postgres)
        syncWriter = new FlatPersonOverrideWriter(hub.db.postgres)
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
