import { PluginEvent, Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { TopicMessage } from '../../../src/kafka/producer'
import {
    Database,
    Hub,
    InternalPerson,
    PropertiesLastOperation,
    PropertiesLastUpdatedAt,
    Team,
} from '../../../src/types'
import { DependencyUnavailableError } from '../../../src/utils/db/error'
import { closeHub, createHub } from '../../../src/utils/db/hub'
import { PostgresUse, TransactionClient } from '../../../src/utils/db/postgres'
import { defaultRetryConfig } from '../../../src/utils/retries'
import { UUIDT } from '../../../src/utils/utils'
import { uuidFromDistinctId } from '../../../src/worker/ingestion/person-uuid'
import { MeasuringPersonsStoreForBatch } from '../../../src/worker/ingestion/persons/measuring-person-store'
import { PersonContext } from '../../../src/worker/ingestion/persons/person-context'
import { PersonEventProcessor } from '../../../src/worker/ingestion/persons/person-event-processor'
import { PersonMergeService } from '../../../src/worker/ingestion/persons/person-merge-service'
import { PersonPropertyService } from '../../../src/worker/ingestion/persons/person-property-service'
import { delayUntilEventIngested } from '../../helpers/clickhouse'
import { createOrganization, createTeam, fetchPostgresPersons, getTeam, insertRow } from '../../helpers/sql'

jest.setTimeout(30000)

const timestamp = DateTime.fromISO('2020-01-01T12:00:05.200Z').toUTC()
const timestamp2 = DateTime.fromISO('2020-02-02T12:00:05.200Z').toUTC()
const timestampch = '2020-01-01 12:00:05.000'

async function createPerson(
    hub: Hub,
    createdAt: DateTime,
    properties: Properties,
    propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
    propertiesLastOperation: PropertiesLastOperation,
    teamId: number,
    isUserId: number | null,
    isIdentified: boolean,
    uuid: string,
    distinctIds?: { distinctId: string; version?: number }[],
    tx?: TransactionClient
): Promise<InternalPerson> {
    const [person, kafkaMessages] = await hub.db.createPerson(
        createdAt,
        properties,
        propertiesLastUpdatedAt,
        propertiesLastOperation,
        teamId,
        isUserId,
        isIdentified,
        uuid,
        distinctIds,
        tx
    )
    await hub.db.kafkaProducer.queueMessages(kafkaMessages)
    return person
}

describe('PersonState.processEvent()', () => {
    let hub: Hub

    let teamId: number
    let mainTeam: Team
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
        hub = await createHub({})
        await hub.db.clickhouseQuery('SYSTEM STOP MERGES')

        organizationId = await createOrganization(hub.db.postgres)
    })

    beforeEach(async () => {
        teamId = await createTeam(hub.db.postgres, organizationId)
        mainTeam = (await getTeam(hub, teamId))!

        newUserUuid = uuidFromDistinctId(teamId, newUserDistinctId)
        oldUserUuid = uuidFromDistinctId(teamId, oldUserDistinctId)
        firstUserUuid = uuidFromDistinctId(teamId, firstUserDistinctId)
        secondUserUuid = uuidFromDistinctId(teamId, secondUserDistinctId)

        jest.spyOn(hub.db, 'fetchPerson')
        jest.spyOn(hub.db, 'updatePerson')

        jest.useFakeTimers({ advanceTimers: 50 })
        defaultRetryConfig.RETRY_INTERVAL_DEFAULT = 0
    })

    afterEach(() => {
        jest.clearAllTimers()
    })

    afterAll(async () => {
        await closeHub(hub)
        await hub.db.clickhouseQuery('SYSTEM START MERGES')
    })

    function personProcessor(
        event: Partial<PluginEvent>,
        propertyService?: PersonPropertyService,
        mergeService?: PersonMergeService,
        customHub?: Hub,
        processPerson = true,
        timestampParam = timestamp,
        team = mainTeam
    ) {
        const fullEvent = {
            team_id: teamId,
            properties: {},
            ...event,
        }

        const personsStore = new MeasuringPersonsStoreForBatch(customHub ? customHub.db : hub.db)

        const context = new PersonContext(
            fullEvent as any,
            team,
            event.distinct_id!,
            timestampParam,
            processPerson,
            customHub ? customHub.db.kafkaProducer : hub.db.kafkaProducer,
            personsStore,
            0
        )
        const processor = new PersonEventProcessor(
            context,
            propertyService ?? new PersonPropertyService(context),
            mergeService ?? new PersonMergeService(context)
        )
        return processor
    }

    function personPropertyService(
        event: Partial<PluginEvent>,
        customHub?: Hub,
        processPerson = true,
        timestampParam = timestamp,
        team = mainTeam,
        updateIsIdentified: boolean = false
    ) {
        const fullEvent = {
            team_id: teamId,
            properties: {},
            ...event,
        }

        const personsStore = new MeasuringPersonsStoreForBatch(customHub ? customHub.db : hub.db)

        const context = new PersonContext(
            fullEvent as any,
            team,
            event.distinct_id!,
            timestampParam,
            processPerson,
            customHub ? customHub.db.kafkaProducer : hub.db.kafkaProducer,
            personsStore,
            0
        )
        context.updateIsIdentified = updateIsIdentified
        return new PersonPropertyService(context)
    }

    function personMergeService(
        event: Partial<PluginEvent>,
        customHub?: Hub,
        processPerson = true,
        timestampParam = timestamp,
        team = mainTeam
    ) {
        const fullEvent = {
            team_id: teamId,
            properties: {},
            ...event,
        }

        const personsStore = new MeasuringPersonsStoreForBatch(customHub ? customHub.db : hub.db)

        const context = new PersonContext(
            fullEvent as any,
            team,
            event.distinct_id!,
            timestampParam,
            processPerson,
            customHub ? customHub.db.kafkaProducer : hub.db.kafkaProducer,
            personsStore,
            0
        )
        return new PersonMergeService(context)
    }

    const sortPersons = (persons: InternalPerson[]) => persons.sort((a, b) => Number(a.id) - Number(b.id))

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
            const [personPrimaryTeam, kafkaAcks] = await personPropertyService({
                event: '$pageview',
                distinct_id: newUserDistinctId,
                uuid: event_uuid,
            }).updateProperties()

            const otherTeamId = await createTeam(hub.db.postgres, organizationId)
            const otherTeam = (await getTeam(hub, otherTeamId))!
            teamId = otherTeamId
            const [personOtherTeam, kafkaAcksOther] = await personPropertyService(
                {
                    event: '$pageview',
                    distinct_id: newUserDistinctId,
                    uuid: event_uuid,
                },
                undefined,
                true,
                timestamp,
                otherTeam
            ).updateProperties()

            await hub.db.kafkaProducer.flush()
            await kafkaAcks
            await kafkaAcksOther

            expect(personPrimaryTeam.uuid).toEqual(uuidFromDistinctId(primaryTeamId, newUserDistinctId))
            expect(personOtherTeam.uuid).toEqual(uuidFromDistinctId(otherTeamId, newUserDistinctId))
            expect(personPrimaryTeam.uuid).not.toEqual(personOtherTeam.uuid)
        })

        it('returns an ephemeral user object when $process_person_profile=false', async () => {
            const event_uuid = new UUIDT().toString()

            const hubParam = undefined
            const processPerson = false
            const [fakePerson, kafkaAcks] = await personProcessor(
                {
                    event: '$pageview',
                    distinct_id: newUserDistinctId,
                    uuid: event_uuid,
                    properties: { $set: { should_be_dropped: 100 } },
                },
                undefined,
                undefined,
                hubParam,
                processPerson
            ).processEvent()
            await hub.db.kafkaProducer.flush()
            await kafkaAcks

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

        it('overrides are created only when distinct_id is in posthog_personlessdistinctid', async () => {
            // oldUserDistinctId exists, and 'old2' will merge into it, but not create an override
            await createPerson(hub, timestamp, {}, {}, {}, teamId, null, false, oldUserUuid, [
                { distinctId: oldUserDistinctId },
            ])

            // newUserDistinctId exists, and 'new2' will merge into it, and will create an override
            await createPerson(hub, timestamp, {}, {}, {}, teamId, null, false, newUserUuid, [
                { distinctId: newUserDistinctId },
            ])

            await hub.db.addPersonlessDistinctId(teamId, 'new2')

            const hubParam = undefined
            const processPerson = true
            const [_person, kafkaAcks] = await personProcessor(
                {
                    event: '$identify',
                    distinct_id: oldUserDistinctId,
                    properties: {
                        $anon_distinct_id: 'old2',
                    },
                },
                undefined,
                undefined,
                hubParam,
                processPerson
            ).processEvent()

            const [_person2, kafkaAcks2] = await personProcessor(
                {
                    event: '$identify',
                    distinct_id: newUserDistinctId,
                    properties: {
                        $anon_distinct_id: 'new2',
                    },
                },
                undefined,
                undefined,
                hubParam,
                processPerson
            ).processEvent()

            await hub.db.kafkaProducer.flush()
            await kafkaAcks
            await kafkaAcks2

            // new2 has an override, because it was in posthog_personlessdistinctid
            await delayUntilEventIngested(() => fetchOverridesForDistinctId('new2'))
            const chOverrides = await fetchOverridesForDistinctId('new2')
            expect(chOverrides.length).toEqual(1)
            expect(chOverrides).toEqual(
                expect.arrayContaining([
                    expect.objectContaining({
                        distinct_id: 'new2',
                        person_id: newUserUuid,
                        version: 1,
                    }),
                ])
            )

            // old2 has no override, because it wasn't in posthog_personlessdistinctid
            const chOverridesOld = await fetchOverridesForDistinctId('old2')
            expect(chOverridesOld.length).toEqual(0)
        })

        it('force_upgrade works', async () => {
            const [_, oldPersonKafkaMessages] = await hub.db.createPerson(
                timestamp,
                {},
                {},
                {},
                teamId,
                null,
                false,
                oldUserUuid,
                [{ distinctId: oldUserDistinctId }]
            )
            await hub.db.kafkaProducer.queueMessages(oldPersonKafkaMessages)

            const hubParam = undefined
            let processPerson = true
            const [_person, kafkaAcks] = await personProcessor(
                {
                    event: '$identify',
                    distinct_id: newUserDistinctId,
                    properties: {
                        $anon_distinct_id: oldUserDistinctId,
                    },
                },
                undefined,
                undefined,
                hubParam,
                processPerson
            ).processEvent()
            await hub.db.kafkaProducer.flush()
            await kafkaAcks

            // Using the `distinct_id` again with `processPerson=false` results in
            // `force_upgrade=true` and real Person `uuid` and `created_at`
            processPerson = false
            const event_uuid = new UUIDT().toString()
            const timestampParam = timestamp.plus({ minutes: 5 }) // Event needs to happen after Person creation
            const [fakePerson, kafkaAcks2] = await personProcessor(
                {
                    event: '$pageview',
                    distinct_id: newUserDistinctId,
                    uuid: event_uuid,
                    properties: { $set: { should_be_dropped: 100 } },
                },
                undefined,
                undefined,
                hubParam,
                processPerson,
                timestampParam
            ).processEvent()
            await hub.db.kafkaProducer.flush()
            await kafkaAcks2

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

        it('force_upgrade is ignored if team.person_processing_opt_out is true', async () => {
            mainTeam.person_processing_opt_out = true
            const [_, oldPersonKafkaMessages] = await hub.db.createPerson(
                timestamp,
                {},
                {},
                {},
                teamId,
                null,
                false,
                oldUserUuid,
                [{ distinctId: oldUserDistinctId }]
            )
            await hub.db.kafkaProducer.queueMessages(oldPersonKafkaMessages)

            const hubParam = undefined
            let processPerson = true
            const [_person, kafkaAcks] = await personProcessor(
                {
                    event: '$identify',
                    distinct_id: newUserDistinctId,
                    properties: {
                        $anon_distinct_id: oldUserDistinctId,
                    },
                },
                undefined,
                undefined,
                hubParam,
                processPerson
            ).processEvent()
            await hub.db.kafkaProducer.flush()
            await kafkaAcks

            // Using the `distinct_id` again with `processPerson=false` results in
            // `force_upgrade=true` and real Person `uuid` and `created_at`
            processPerson = false
            const event_uuid = new UUIDT().toString()
            const timestampParam = timestamp.plus({ minutes: 5 }) // Event needs to happen after Person creation
            const [fakePerson, kafkaAcks2] = await personProcessor(
                {
                    event: '$pageview',
                    distinct_id: newUserDistinctId,
                    uuid: event_uuid,
                    properties: { $set: { should_be_dropped: 100 } },
                },
                undefined,
                undefined,
                hubParam,
                processPerson,
                timestampParam
            ).processEvent()
            await hub.db.kafkaProducer.flush()
            await kafkaAcks2

            expect(fakePerson.force_upgrade).toBeUndefined()
        })

        it('creates person if they are new', async () => {
            const event_uuid = new UUIDT().toString()
            const [person, kafkaAcks] = await personPropertyService({
                event: '$pageview',
                distinct_id: newUserDistinctId,
                uuid: event_uuid,
                // `null_byte` validates that `sanitizeJsonbValue` is working as expected
                properties: { $set: { null_byte: '\u0000' } },
            }).updateProperties()
            await hub.db.kafkaProducer.flush()
            await kafkaAcks

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(String),
                    uuid: newUserUuid,
                    properties: { $creator_event_uuid: event_uuid, null_byte: '\uFFFD' },
                    created_at: timestamp,
                    version: 0,
                    is_identified: false,
                })
            )

            expect(hub.db.fetchPerson).toHaveBeenCalledTimes(1)
            expect(hub.db.updatePerson).not.toHaveBeenCalled()

            // verify Postgres persons
            const persons = sortPersons(await fetchPostgresPersonsH())
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(person)

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining([newUserDistinctId]))
        })

        it('does not attach existing person properties to $process_person_profile=false events', async () => {
            const originalEventUuid = new UUIDT().toString()
            const [person, kafkaAcks] = await personProcessor({
                event: '$pageview',
                distinct_id: newUserDistinctId,
                uuid: originalEventUuid,
                properties: { $set: { c: 420 } },
            }).processEvent()
            await hub.db.kafkaProducer.flush()
            await kafkaAcks

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(String),
                    uuid: newUserUuid,
                    properties: { $creator_event_uuid: originalEventUuid, c: 420 },
                    created_at: timestamp,
                    version: 0,
                    is_identified: false,
                })
            )

            // verify Postgres persons
            const persons = sortPersons(await fetchPostgresPersonsH())
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(person)

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining([newUserDistinctId]))

            // OK, a person now exists with { c: 420 }, let's prove the properties come back out
            // of the DB.
            const [personVerifyProps] = await personProcessor({
                event: '$pageview',
                distinct_id: newUserDistinctId,
                uuid: new UUIDT().toString(),
                properties: {},
            }).processEvent()
            expect(personVerifyProps.properties).toEqual({ $creator_event_uuid: originalEventUuid, c: 420 })

            // But they don't when $process_person_profile=false
            const [processPersonFalseResult] = await personProcessor(
                {
                    event: '$pageview',
                    distinct_id: newUserDistinctId,
                    uuid: new UUIDT().toString(),
                    properties: {},
                },
                undefined,
                undefined,
                hub,
                false
            ).processEvent()
            expect(processPersonFalseResult.properties).toEqual({})
        })

        it('handles person being created in a race condition', async () => {
            const [_, newPersonKafkaMessages] = await hub.db.createPerson(
                timestamp,
                {},
                {},
                {},
                teamId,
                null,
                false,
                newUserUuid,
                [{ distinctId: newUserDistinctId }]
            )
            await hub.db.kafkaProducer.queueMessages(newPersonKafkaMessages)

            jest.spyOn(hub.db, 'fetchPerson').mockImplementationOnce(() => {
                return Promise.resolve(undefined)
            })

            const [person, kafkaAcks] = await personPropertyService({
                event: '$pageview',
                distinct_id: newUserDistinctId,
            }).handleUpdate()
            await hub.db.kafkaProducer.flush()
            await kafkaAcks

            // if creation fails we should return the person that another thread already created
            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(String),
                    uuid: newUserUuid,
                    properties: {},
                    created_at: timestamp,
                    version: 0,
                    is_identified: false,
                })
            )
            expect(hub.db.updatePerson).not.toHaveBeenCalled()
            // verify Postgres persons
            const persons = sortPersons(await fetchPostgresPersonsH())
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(person)

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(person)
            expect(distinctIds).toEqual(expect.arrayContaining([newUserDistinctId]))
        })

        it('handles person being created in a race condition updates properties if needed', async () => {
            const [_, newPersonKafkaMessages] = await hub.db.createPerson(
                timestamp,
                { b: 3, c: 4 },
                {},
                {},
                teamId,
                null,
                false,
                newUserUuid,
                [{ distinctId: newUserDistinctId }]
            )
            await hub.db.kafkaProducer.queueMessages(newPersonKafkaMessages)

            jest.spyOn(hub.db, 'fetchPerson').mockImplementationOnce(() => {
                return Promise.resolve(undefined)
            })

            const [person, kafkaAcks] = await personPropertyService({
                event: '$pageview',
                distinct_id: newUserDistinctId,
                properties: {
                    $set_once: { c: 3, e: 4 },
                    $set: { b: 4 },
                },
            }).handleUpdate()
            await hub.db.kafkaProducer.flush()
            await kafkaAcks

            // if creation fails we should return the person that another thread already created
            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(String),
                    uuid: newUserUuid,
                    properties: { b: 4, c: 4, e: 4 },
                    created_at: timestamp,
                    version: 1,
                    is_identified: false,
                })
            )
            expect(hub.db.updatePerson).toHaveBeenCalledTimes(1)
            // verify Postgres persons
            const persons = sortPersons(await fetchPostgresPersonsH())
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(person)

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(person)
            expect(distinctIds).toEqual(expect.arrayContaining([newUserDistinctId]))
        })

        it('creates person with properties', async () => {
            const [person, kafkaAcks] = await personPropertyService({
                event: '$pageview',
                distinct_id: newUserDistinctId,
                properties: {
                    $set_once: { a: 1, b: 2 },
                    $set: { b: 3, c: 4 },
                },
            }).updateProperties()
            await hub.db.kafkaProducer.flush()
            await kafkaAcks

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(String),
                    uuid: newUserUuid,
                    properties: { a: 1, b: 3, c: 4 },
                    created_at: timestamp,
                    version: 0,
                    is_identified: false,
                })
            )

            expect(hub.db.fetchPerson).toHaveBeenCalledTimes(1)
            expect(hub.db.updatePerson).not.toHaveBeenCalled()

            // verify Postgres persons
            const persons = sortPersons(await fetchPostgresPersonsH())
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(person)

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining([newUserDistinctId]))
        })
    })

    describe('on person update', () => {
        it('updates person properties', async () => {
            await createPerson(hub, timestamp, { b: 3, c: 4, toString: {} }, {}, {}, teamId, null, false, newUserUuid, [
                { distinctId: newUserDistinctId },
            ])
            const [person, kafkaAcks] = await personPropertyService({
                event: '$pageview',
                distinct_id: newUserDistinctId,
                properties: {
                    $set_once: { c: 3, e: 4 },
                    $set: { b: 4, toString: 1, null_byte: '\u0000' },
                },
            }).updateProperties()
            await hub.db.kafkaProducer.flush()
            await kafkaAcks

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(String),
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
            const persons = sortPersons(await fetchPostgresPersonsH())
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(person)
        })

        it.each(['$$heatmap', '$exception'])('does not update person properties for %s', async (event: string) => {
            const originalPersonProperties = { b: 3, c: 4, toString: {} }

            await createPerson(hub, timestamp, originalPersonProperties, {}, {}, teamId, null, false, newUserUuid, [
                { distinctId: newUserDistinctId },
            ])

            const [person, kafkaAcks] = await personPropertyService({
                event: event,
                distinct_id: newUserDistinctId,
                properties: {
                    $set_once: { c: 3, e: 4 },
                    $set: { b: 4, toString: 1, null_byte: '\u0000' },
                },
            }).updateProperties()
            await hub.db.kafkaProducer.flush()
            await kafkaAcks

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(String),
                    uuid: newUserUuid,
                    properties: originalPersonProperties,
                    created_at: timestamp,
                    version: 0,
                    is_identified: false,
                })
            )

            expect(hub.db.fetchPerson).toHaveBeenCalledTimes(1)

            // verify Postgres persons
            const persons = sortPersons(await fetchPostgresPersonsH())
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(person)
        })

        it('updates person properties - no update if not needed', async () => {
            await createPerson(hub, timestamp, { $current_url: 123 }, {}, {}, teamId, null, false, newUserUuid, [
                { distinctId: newUserDistinctId },
            ])
            const [person, kafkaAcks] = await personPropertyService({
                event: '$pageview',
                distinct_id: newUserDistinctId,
                properties: {
                    $set: { $current_url: 4 },
                },
            }).updateProperties()
            await hub.db.kafkaProducer.flush()
            await kafkaAcks

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(String),
                    uuid: newUserUuid,
                    properties: { $current_url: 4 }, // Here we keep 4 for passing forward to PoE
                    created_at: timestamp,
                    version: 0,
                    is_identified: false,
                })
            )

            expect(hub.db.fetchPerson).toHaveBeenCalledTimes(1)

            // verify Postgres persons
            const persons = sortPersons(await fetchPostgresPersonsH())
            expect(persons).toEqual([
                expect.objectContaining({
                    id: expect.any(String),
                    uuid: newUserUuid,
                    properties: { $current_url: 123 }, // We didn 't update this as it's auto added and it's not a person event
                    created_at: timestamp,
                    version: 0,
                    is_identified: false,
                }),
            ])
        })

        it('updates person properties - always update for person events', async () => {
            await createPerson(hub, timestamp, { $current_url: 123 }, {}, {}, teamId, null, false, newUserUuid, [
                { distinctId: newUserDistinctId },
            ])

            const [person, kafkaAcks] = await personPropertyService({
                event: '$set',
                distinct_id: newUserDistinctId,
                properties: {
                    $set: { $current_url: 4 },
                },
            }).updateProperties()
            await hub.db.kafkaProducer.flush()
            await kafkaAcks

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(String),
                    uuid: newUserUuid,
                    properties: { $current_url: 4 }, // Here we keep 4 for passing forward to PoE
                    created_at: timestamp,
                    version: 1,
                    is_identified: false,
                })
            )

            expect(hub.db.fetchPerson).toHaveBeenCalledTimes(1)

            // verify Postgres persons
            const persons = sortPersons(await fetchPostgresPersonsH())
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(person) // We updated PG as it's a person event
        })

        it('updates person properties - always update if undefined before', async () => {
            await createPerson(hub, timestamp, {}, {}, {}, teamId, null, false, newUserUuid, [
                { distinctId: newUserDistinctId },
            ])

            const [person, kafkaAcks] = await personPropertyService({
                event: '$pageview',
                distinct_id: newUserDistinctId,
                properties: {
                    $set: { $initial_current_url: 4 },
                },
            }).updateProperties()
            await hub.db.kafkaProducer.flush()
            await kafkaAcks

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(String),
                    uuid: newUserUuid,
                    properties: { $initial_current_url: 4 }, // Here we keep 4 for passing forward to PoE
                    created_at: timestamp,
                    version: 1,
                    is_identified: false,
                })
            )

            expect(hub.db.fetchPerson).toHaveBeenCalledTimes(1)

            // verify Postgres persons
            const persons = sortPersons(await fetchPostgresPersonsH())
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(person) // We updated PG as it was undefined before
        })

        it('updates person properties - always update for initial properties', async () => {
            await createPerson(
                hub,
                timestamp,
                { $initial_current_url: 123 },
                {},
                {},
                teamId,
                null,
                false,
                newUserUuid,
                [{ distinctId: newUserDistinctId }]
            )

            const [person, kafkaAcks] = await personPropertyService({
                event: '$pageview',
                distinct_id: newUserDistinctId,
                properties: {
                    $set: { $initial_current_url: 4 },
                },
            }).updateProperties()
            await hub.db.kafkaProducer.flush()
            await kafkaAcks

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(String),
                    uuid: newUserUuid,
                    properties: { $initial_current_url: 4 }, // Here we keep 4 for passing forward to PoE
                    created_at: timestamp,
                    version: 1,
                    is_identified: false,
                })
            )

            expect(hub.db.fetchPerson).toHaveBeenCalledTimes(1)

            // verify Postgres persons
            const persons = sortPersons(await fetchPostgresPersonsH())
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(person) // We updated PG as it's an initial property
        })

        it('updating with cached person data shortcuts to update directly', async () => {
            const personInitial = await createPerson(
                hub,
                timestamp,
                { b: 3, c: 4 },
                {},
                {},
                teamId,
                null,
                false,
                newUserUuid,
                [{ distinctId: newUserDistinctId }]
            )
            const event = {
                event: '$pageview',
                distinct_id: newUserDistinctId,
                properties: {
                    $set_once: { c: 3, e: 4 },
                    $set: { b: 4 },
                },
            }

            // create mock merge service,
            const mergeService = personMergeService(event)
            jest.spyOn(mergeService, 'handleIdentifyOrAlias').mockReturnValue(
                Promise.resolve([personInitial, Promise.resolve()])
            )

            const personS = personProcessor(event, undefined, mergeService)
            const [person, kafkaAcks] = await personS.processEvent()
            await hub.db.kafkaProducer.flush()
            await kafkaAcks

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(String),
                    uuid: newUserUuid,
                    properties: { b: 4, c: 4, e: 4 },
                    created_at: timestamp,
                    version: 1,
                    is_identified: false,
                })
            )

            expect(hub.db.fetchPerson).toHaveBeenCalledTimes(0)

            // verify Postgres persons
            const persons = sortPersons(await fetchPostgresPersonsH())
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(person)
        })

        it('does not update person if not needed', async () => {
            await createPerson(hub, timestamp, { b: 3, c: 4 }, {}, {}, teamId, null, false, newUserUuid, [
                { distinctId: newUserDistinctId },
            ])

            const [person, kafkaAcks] = await personPropertyService({
                event: '$pageview',
                distinct_id: newUserDistinctId,
                properties: {
                    $set_once: { c: 3 },
                    $set: { b: 3 },
                },
            }).updateProperties()
            await hub.db.kafkaProducer.flush()
            await kafkaAcks

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(String),
                    uuid: newUserUuid,
                    properties: { b: 3, c: 4 },
                    created_at: timestamp,
                    version: 0,
                    is_identified: false,
                })
            )

            expect(hub.db.fetchPerson).toHaveBeenCalledTimes(1)
            expect(hub.db.updatePerson).not.toHaveBeenCalled()

            // verify Postgres persons
            const persons = sortPersons(await fetchPostgresPersonsH())
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(person)
        })

        it('marks user as is_identified', async () => {
            await createPerson(hub, timestamp, {}, {}, {}, teamId, null, false, newUserUuid, [
                { distinctId: newUserDistinctId },
            ])

            const personS = personPropertyService(
                {
                    event: '$pageview',
                    distinct_id: newUserDistinctId,
                    properties: {},
                },
                undefined,
                true,
                timestamp,
                mainTeam,
                true
            )

            const [person, kafkaAcks] = await personS.updateProperties()
            await hub.db.kafkaProducer.flush()
            await kafkaAcks
            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(String),
                    uuid: newUserUuid,
                    properties: {},
                    created_at: timestamp,
                    version: 1,
                    is_identified: true,
                })
            )

            expect(hub.db.fetchPerson).toHaveBeenCalledTimes(1)
            expect(hub.db.updatePerson).toHaveBeenCalledTimes(1)

            // verify Postgres persons
            const persons = sortPersons(await fetchPostgresPersonsH())
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(person)

            await personS.updateProperties()
            expect(hub.db.updatePerson).toHaveBeenCalledTimes(1)
        })

        it('handles race condition when person provided has been merged', async () => {
            // TODO: we don't handle this currently person having been changed / updated properties can get overridden
            // Pass in a person, but another thread merges it - we shouldn't error in this case, but instead if we couldn't update we should retry?
            const mergeDeletedPerson: InternalPerson = {
                created_at: timestamp,
                version: 0,
                id: '0',
                team_id: teamId,
                properties: { a: 5, b: 7 },
                is_user_id: 0,
                is_identified: false,
                uuid: uuidFromDistinctId(teamId, 'deleted-user'),
                properties_last_updated_at: {},
                properties_last_operation: {},
            }
            await createPerson(hub, timestamp, { a: 6, c: 8 }, {}, {}, teamId, null, true, newUserUuid, [
                { distinctId: newUserDistinctId },
                { distinctId: oldUserDistinctId },
            ]) // the merged Person

            const event = {
                event: '$pageview',
                distinct_id: newUserDistinctId,
                properties: { $set: { a: 7, d: 9 } },
            }
            // create mock merge service
            const mergeService = personMergeService(event)
            jest.spyOn(mergeService, 'handleIdentifyOrAlias').mockReturnValue(
                Promise.resolve([mergeDeletedPerson, Promise.resolve()])
            )

            const personS = personProcessor(event, undefined, mergeService)

            const [person, kafkaAcks] = await personS.processEvent()
            await hub.db.kafkaProducer.flush()
            await kafkaAcks

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(String),
                    uuid: newUserUuid,
                    properties: { a: 7, c: 8, d: 9 },
                    created_at: timestamp,
                    version: 1,
                    is_identified: true,
                })
            )

            expect(hub.db.fetchPerson).toHaveBeenCalledTimes(1)
            expect(hub.db.updatePerson).toHaveBeenCalledTimes(2)

            // verify Postgres persons
            const persons = sortPersons(await fetchPostgresPersonsH())
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(person)
        })
    })

    describe('on $identify event', () => {
        it(`no-op when $anon_distinct_id not passed`, async () => {
            const [person, kafkaAcks] = await personMergeService({
                event: '$identify',
                distinct_id: newUserDistinctId,
                properties: {
                    $set: { foo: 'bar' },
                },
            }).handleIdentifyOrAlias()
            await hub.db.kafkaProducer.flush()
            await kafkaAcks

            expect(person).toEqual(undefined)
            const persons = await fetchPostgresPersonsH()
            expect(persons.length).toEqual(0)
        })

        it(`creates person with both distinct_ids and marks user as is_identified when $anon_distinct_id passed`, async () => {
            const [person, kafkaAcks] = await personMergeService({
                event: '$identify',
                distinct_id: newUserDistinctId,
                properties: {
                    $set: { foo: 'bar' },
                    $anon_distinct_id: oldUserDistinctId,
                },
            }).handleIdentifyOrAlias()
            await hub.db.kafkaProducer.flush()
            await kafkaAcks

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(String),
                    uuid: newUserUuid,
                    properties: { foo: 'bar' },
                    created_at: timestamp,
                    version: 0,
                    is_identified: true,
                })
            )

            expect(hub.db.updatePerson).not.toHaveBeenCalled()

            // verify Postgres persons
            const persons = await fetchPostgresPersonsH()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(person)

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining([oldUserDistinctId, newUserDistinctId]))
        })

        it(`marks is_identified to be updated when no changes to distinct_ids but $anon_distinct_id passe`, async () => {
            await createPerson(hub, timestamp, {}, {}, {}, teamId, null, false, newUserUuid, [
                { distinctId: newUserDistinctId },
                { distinctId: oldUserDistinctId },
            ])
            const personS = personMergeService({
                event: '$identify',
                distinct_id: newUserDistinctId,
                properties: {
                    $anon_distinct_id: oldUserDistinctId,
                },
            })
            const [person, kafkaAcks] = await personS.handleIdentifyOrAlias()
            await hub.db.kafkaProducer.flush()
            await kafkaAcks

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(String),
                    uuid: newUserUuid,
                    properties: {},
                    created_at: timestamp,
                    version: 0,
                    is_identified: false,
                })
            )
            expect(personS.getUpdateIsIdentified()).toBeTruthy()

            // verify Postgres persons
            const persons = await fetchPostgresPersonsH()
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(person)
        })

        it(`add distinct id and marks user is_identified when passed $anon_distinct_id person does not exists and distinct_id does`, async () => {
            await createPerson(hub, timestamp, {}, {}, {}, teamId, null, false, newUserUuid, [
                { distinctId: newUserDistinctId },
            ])
            const personS = personMergeService({
                event: '$identify',
                distinct_id: newUserDistinctId,
                properties: {
                    $anon_distinct_id: oldUserDistinctId,
                },
            })
            const [person, kafkaAcks] = await personS.handleIdentifyOrAlias()
            await hub.db.kafkaProducer.flush()
            await kafkaAcks

            const persons = await fetchPostgresPersonsH()
            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(String),
                    uuid: newUserUuid,
                    properties: {},
                    created_at: timestamp,
                    version: 0,
                    is_identified: false,
                })
            )
            expect(personS.getUpdateIsIdentified()).toBeTruthy()

            // verify Postgres persons
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(person)

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining([oldUserDistinctId, newUserDistinctId]))
        })

        it(`add distinct id and marks user as is_identified when passed $anon_distinct_id person exists and distinct_id does not`, async () => {
            await createPerson(hub, timestamp, {}, {}, {}, teamId, null, false, oldUserUuid, [
                { distinctId: oldUserDistinctId },
            ])

            const personS = personMergeService({
                event: '$identify',
                distinct_id: newUserDistinctId,
                properties: {
                    $anon_distinct_id: oldUserDistinctId,
                },
            })
            const [person, kafkaAcks] = await personS.handleIdentifyOrAlias()
            await hub.db.kafkaProducer.flush()
            await kafkaAcks

            const persons = await fetchPostgresPersonsH()

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(String),
                    uuid: oldUserUuid,
                    properties: {},
                    created_at: timestamp,
                    version: 0,
                    is_identified: false,
                })
            )
            expect(personS.getUpdateIsIdentified()).toBeTruthy()

            // verify Postgres persons
            expect(persons.length).toEqual(1)
            expect(persons[0]).toEqual(person)

            // verify Postgres distinct_ids
            const distinctIds = await hub.db.fetchDistinctIdValues(persons[0])
            expect(distinctIds).toEqual(expect.arrayContaining([oldUserDistinctId, newUserDistinctId]))
        })

        it(`merge into distinct_id person and marks user as is_identified when both persons have is_identified false`, async () => {
            await createPerson(hub, timestamp, {}, {}, {}, teamId, null, false, oldUserUuid, [
                { distinctId: oldUserDistinctId },
            ])
            await createPerson(hub, timestamp2, {}, {}, {}, teamId, null, false, newUserUuid, [
                { distinctId: newUserDistinctId },
            ])

            const [person, kafkaAcks] = await personMergeService({
                event: '$identify',
                distinct_id: newUserDistinctId,
                properties: {
                    $anon_distinct_id: oldUserDistinctId,
                },
            }).handleIdentifyOrAlias()
            await hub.db.kafkaProducer.flush()
            await kafkaAcks

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(String),
                    uuid: expect.any(String),
                    properties: {},
                    created_at: timestamp,
                    version: 1,
                    is_identified: true,
                })
            )

            // verify Postgres persons
            const persons = sortPersons(await fetchPostgresPersonsH())
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
            await createPerson(hub, timestamp, {}, {}, {}, teamId, null, false, oldUserUuid, [
                { distinctId: oldUserDistinctId },
            ])
            await createPerson(hub, timestamp2, {}, {}, {}, teamId, null, true, newUserUuid, [
                { distinctId: newUserDistinctId },
            ])

            const [person, kafkaAcks] = await personMergeService({
                event: '$identify',
                distinct_id: newUserDistinctId,
                properties: {
                    $anon_distinct_id: oldUserDistinctId,
                },
            }).handleIdentifyOrAlias()
            await hub.db.kafkaProducer.flush()
            await kafkaAcks

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(String),
                    uuid: expect.any(String),
                    properties: {},
                    created_at: timestamp,
                    version: 1,
                    is_identified: true,
                })
            )

            // verify Postgres persons
            const persons = sortPersons(await fetchPostgresPersonsH())
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
            await createPerson(hub, timestamp, {}, {}, {}, teamId, null, true, oldUserUuid, [
                { distinctId: oldUserDistinctId },
            ])
            await createPerson(hub, timestamp2, {}, {}, {}, teamId, null, false, newUserUuid, [
                { distinctId: newUserDistinctId },
            ])

            const personS = personMergeService({
                event: '$identify',
                distinct_id: newUserDistinctId,
                properties: {
                    $anon_distinct_id: oldUserDistinctId,
                },
            })
            const [person, kafkaAcks] = await personS.handleIdentifyOrAlias()
            await hub.db.kafkaProducer.flush()
            await kafkaAcks

            expect(personS.getUpdateIsIdentified()).toBeTruthy()
            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(String),
                    uuid: newUserUuid,
                    properties: {},
                    created_at: timestamp2,
                    version: 0,
                    is_identified: false,
                })
            )

            // verify Postgres persons
            const persons = sortPersons(await fetchPostgresPersonsH())
            expect(persons.length).toEqual(2)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    id: expect.any(String),
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
            await createPerson(hub, timestamp, {}, {}, {}, teamId, null, true, oldUserUuid, [
                { distinctId: oldUserDistinctId },
            ])
            await createPerson(hub, timestamp2, {}, {}, {}, teamId, null, true, newUserUuid, [
                { distinctId: newUserDistinctId },
            ])
            const [person, kafkaAcks] = await personMergeService({
                event: '$identify',
                distinct_id: newUserDistinctId,
                properties: {
                    $anon_distinct_id: oldUserDistinctId,
                },
            }).handleIdentifyOrAlias()
            await hub.db.kafkaProducer.flush()
            await kafkaAcks

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(String),
                    uuid: newUserUuid,
                    properties: {},
                    created_at: timestamp2,
                    version: 0,
                    is_identified: true,
                })
            )

            // verify Postgres persons
            const persons = sortPersons(await fetchPostgresPersonsH())
            expect(persons.length).toEqual(2)
            expect(persons[0]).toEqual(
                expect.objectContaining({
                    id: expect.any(String),
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
            await createPerson(hub, timestamp, { a: 1, b: 2 }, {}, {}, teamId, null, false, oldUserUuid, [
                { distinctId: oldUserDistinctId },
            ])
            await createPerson(hub, timestamp2, { b: 3, c: 4, d: 5 }, {}, {}, teamId, null, false, newUserUuid, [
                { distinctId: newUserDistinctId },
            ])

            const [person, kafkaAcks] = await personMergeService({
                event: '$identify',
                distinct_id: newUserDistinctId,
                properties: {
                    $set: { d: 6, e: 7 },
                    $set_once: { a: 8, f: 9 },
                    $anon_distinct_id: oldUserDistinctId,
                },
            }).handleIdentifyOrAlias()
            await hub.db.kafkaProducer.flush()
            await kafkaAcks

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(String),
                    uuid: expect.any(String),
                    properties: { a: 1, b: 3, c: 4, d: 6, e: 7, f: 9 },
                    created_at: timestamp,
                    version: 1,
                    is_identified: true,
                })
            )

            // verify Postgres persons
            const persons = sortPersons(await fetchPostgresPersonsH())
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
            await createPerson(hub, timestamp, {}, {}, {}, teamId, null, false, oldUserUuid, [
                { distinctId: oldUserDistinctId },
            ])

            // Fake the race by assuming createPerson was called before the addDistinctId creation above
            jest.spyOn(hub.db, 'addDistinctId').mockImplementation(
                async (person, distinctId): Promise<TopicMessage[]> => {
                    await hub.db.createPerson(
                        timestamp,
                        {},
                        {},
                        {},
                        teamId,
                        null,
                        false,
                        uuidFromDistinctId(teamId, distinctId),
                        [{ distinctId }]
                    )

                    return await hub.db.addDistinctId(person, distinctId, 0) // this throws
                }
            )

            const [person, kafkaAcks] = await personMergeService({
                event: '$identify',
                distinct_id: oldUserDistinctId,
                properties: {
                    $anon_distinct_id: newUserDistinctId,
                },
            }).handleIdentifyOrAlias()
            await hub.db.kafkaProducer.flush()
            await kafkaAcks
            jest.spyOn(hub.db, 'addDistinctId').mockRestore() // Necessary for other tests not to fail

            // if creation fails we should return the person that another thread already created
            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(String),
                    uuid: oldUserUuid,
                    properties: {},
                    created_at: timestamp,
                    version: 1,
                    is_identified: true,
                })
            )
            // expect(hub.db.updatePerson).not.toHaveBeenCalled()
            // verify Postgres persons
            const persons = sortPersons(await fetchPostgresPersonsH())
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
            const state: PersonMergeService = personMergeService(
                {
                    event: '$identify',
                    distinct_id: newUserDistinctId,
                    properties: { $anon_distinct_id: oldUserDistinctId },
                },
                hub
            )
            jest.spyOn(state, 'merge').mockImplementation(() => {
                return Promise.resolve([undefined, Promise.resolve()])
            })
            await state.handleIdentifyOrAlias()
            expect(state.merge).toHaveBeenCalledWith(oldUserDistinctId, newUserDistinctId, teamId, timestamp)
            jest.spyOn(state, 'merge').mockRestore()
        })

        it('calls merge on $create_alias as expected', async () => {
            const state: PersonMergeService = personMergeService(
                {
                    event: '$create_alias',
                    distinct_id: newUserDistinctId,
                    properties: { alias: oldUserDistinctId },
                },
                hub
            )
            jest.spyOn(state, 'merge').mockImplementation(() => {
                return Promise.resolve([undefined, Promise.resolve()])
            })

            await state.handleIdentifyOrAlias()
            expect(state.merge).toHaveBeenCalledWith(oldUserDistinctId, newUserDistinctId, teamId, timestamp)
            jest.spyOn(state, 'merge').mockRestore()
        })

        it('calls merge on $merge_dangerously as expected', async () => {
            const state: PersonMergeService = personMergeService(
                {
                    event: '$merge_dangerously',
                    distinct_id: newUserDistinctId,
                    properties: { alias: oldUserDistinctId },
                },
                hub
            )
            jest.spyOn(state, 'merge').mockImplementation(() => {
                return Promise.resolve([undefined, Promise.resolve()])
            })

            await state.handleIdentifyOrAlias()
            expect(state.merge).toHaveBeenCalledWith(oldUserDistinctId, newUserDistinctId, teamId, timestamp)
            jest.spyOn(state, 'merge').mockRestore()
        })
    })

    describe('on $merge_dangerously events', () => {
        // only difference between $merge_dangerously and $identify
        it(`merge_dangerously can merge people when alias id user is identified`, async () => {
            await createPerson(hub, timestamp, {}, {}, {}, teamId, null, true, oldUserUuid, [
                { distinctId: oldUserDistinctId },
            ])
            await createPerson(hub, timestamp2, {}, {}, {}, teamId, null, true, newUserUuid, [
                { distinctId: newUserDistinctId },
            ])
            const [person, kafkaAcks] = await personMergeService({
                event: '$merge_dangerously',
                distinct_id: newUserDistinctId,
                properties: {
                    alias: oldUserDistinctId,
                },
            }).handleIdentifyOrAlias()
            await hub.db.kafkaProducer.flush()
            await kafkaAcks

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(String),
                    uuid: expect.any(String),
                    properties: {},
                    created_at: timestamp,
                    version: 1,
                    is_identified: true,
                })
            )

            // verify Postgres persons
            const persons = sortPersons(await fetchPostgresPersonsH())
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

    describe('illegal aliasing', () => {
        const illegalIds = ['', '   ', 'null', 'undefined', '"undefined"', '[object Object]', '"[object Object]"']
        it.each(illegalIds)('stops $identify if current distinct_id is illegal: `%s`', async (illegalId: string) => {
            const [person] = await personMergeService({
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
            const [person] = await personMergeService({
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
            const [person] = await personMergeService({
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
            const [person] = await personMergeService({
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
            const anonPerson = await createPerson(
                hub,
                timestamp.minus({ hours: 1 }),
                {},
                {},
                {},
                teamId,
                null,
                false,
                uuidFromDistinctId(teamId, 'anonymous_id'),
                [{ distinctId: 'anonymous_id' }]
            )

            const identifiedPerson = await createPerson(
                hub,
                timestamp,
                {},
                {},
                {},
                teamId,
                null,
                false,
                uuidFromDistinctId(teamId, 'new_distinct_id'),
                [{ distinctId: 'new_distinct_id' }]
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
            await personProcessor({
                event: '$identify',
                distinct_id: 'new_distinct_id',
                properties: {
                    $anon_distinct_id: 'anonymous_id',
                    distinct_id: 'new_distinct_id',
                },
            }).processEvent()
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
            const anonPerson = await createPerson(
                hub,
                timestamp.minus({ hours: 1 }),
                {},
                {},
                {},
                teamId,
                null,
                false,
                uuidFromDistinctId(teamId, 'anonymous_id'),
                [{ distinctId: 'anonymous_id' }]
            )

            const identifiedPerson = await createPerson(
                hub,
                timestamp,
                {},
                {},
                {},
                teamId,
                null,
                false,
                uuidFromDistinctId(teamId, 'new_distinct_id'),
                [{ distinctId: 'new_distinct_id' }]
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
            await personProcessor({
                event: '$identify',
                distinct_id: 'new_distinct_id',
                properties: {
                    $anon_distinct_id: 'anonymous_id',
                    distinct_id: 'new_distinct_id',
                },
            }).processEvent()
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
            const anonPerson = await createPerson(
                hub,
                timestamp.minus({ hours: 1 }),
                {},
                {},
                {},
                teamId,
                null,
                false,
                uuidFromDistinctId(teamId, 'anonymous_id'),
                [{ distinctId: 'anonymous_id' }]
            )

            const identifiedPerson = await createPerson(
                hub,
                timestamp,
                {},
                {},
                {},
                teamId,
                null,
                false,
                uuidFromDistinctId(teamId, 'new_distinct_id'),
                [{ distinctId: 'new_distinct_id' }]
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

            await personProcessor({
                event: '$identify',
                distinct_id: 'new_distinct_id',
                properties: {
                    $anon_distinct_id: 'anonymous_id',
                },
            }).processEvent()
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
    describe('on persons merges', () => {
        // For some reason these tests failed if I ran them with a hub shared
        // with other tests, so I'm creating a new hub for each test.
        let hub: Hub

        beforeEach(async () => {
            hub = await createHub({})

            jest.spyOn(hub.db, 'fetchPerson')
            jest.spyOn(hub.db, 'updatePerson')
        })

        afterEach(async () => {
            await closeHub(hub)
        })

        it(`no-op if persons already merged`, async () => {
            await createPerson(hub, timestamp, {}, {}, {}, teamId, null, true, firstUserUuid, [
                { distinctId: firstUserDistinctId },
                { distinctId: secondUserDistinctId },
            ])

            const state: PersonMergeService = personMergeService({}, hub)
            jest.spyOn(hub.db.kafkaProducer, 'queueMessages')
            const [person, kafkaAcks] = await state.merge(secondUserDistinctId, firstUserDistinctId, teamId, timestamp)
            await hub.db.kafkaProducer.flush()
            await kafkaAcks

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(String),
                    uuid: firstUserUuid,
                    properties: {},
                    created_at: timestamp,
                    version: 0,
                    is_identified: true,
                })
            )
            expect(hub.db.updatePerson).not.toHaveBeenCalled()
            expect(hub.db.kafkaProducer.queueMessages).not.toHaveBeenCalled()
        })

        it(`postgres and clickhouse get updated`, async () => {
            const first = await createPerson(hub, timestamp, {}, {}, {}, teamId, null, false, firstUserUuid, [
                { distinctId: firstUserDistinctId },
            ])

            const second = await createPerson(hub, timestamp, {}, {}, {}, teamId, null, false, secondUserUuid, [
                { distinctId: secondUserDistinctId },
            ])

            const state: PersonMergeService = personMergeService({}, hub)
            jest.spyOn(hub.db.kafkaProducer, 'queueMessages')
            const [person, kafkaAcks] = await state.mergePeople({
                mergeInto: first,
                mergeIntoDistinctId: firstUserDistinctId,
                otherPerson: second,
                otherPersonDistinctId: secondUserDistinctId,
            })
            await hub.db.kafkaProducer.flush()
            await kafkaAcks

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(String),
                    uuid: firstUserUuid,
                    properties: {},
                    created_at: timestamp,
                    version: 1,
                    is_identified: true,
                })
            )

            expect(hub.db.updatePerson).toHaveBeenCalledTimes(1)
            expect(hub.db.kafkaProducer.queueMessages).toHaveBeenCalledTimes(1)
            // verify Postgres persons
            const persons = sortPersons(await fetchPostgresPersonsH())
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
            expect(clickHouseDistinctIds).toEqual(expect.arrayContaining([firstUserDistinctId, secondUserDistinctId]))
        })

        it(`throws if postgres unavailable`, async () => {
            const first = await createPerson(hub, timestamp, {}, {}, {}, teamId, null, false, firstUserUuid, [
                { distinctId: firstUserDistinctId },
            ])

            const second = await createPerson(hub, timestamp, {}, {}, {}, teamId, null, false, secondUserUuid, [
                { distinctId: secondUserDistinctId },
            ])
            const state: PersonMergeService = personMergeService({}, hub)
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
            const persons = sortPersons(await fetchPostgresPersonsH())
            expect(persons).toEqual(
                expect.arrayContaining([
                    expect.objectContaining({
                        id: expect.any(String),
                        uuid: firstUserUuid,
                        properties: {},
                        created_at: timestamp,
                        version: 0,
                        is_identified: false,
                    }),
                    expect.objectContaining({
                        id: expect.any(String),
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
            await createPerson(hub, timestamp, {}, {}, {}, teamId, null, false, firstUserUuid, [
                { distinctId: firstUserDistinctId },
            ])
            await createPerson(hub, timestamp, {}, {}, {}, teamId, null, false, secondUserUuid, [
                { distinctId: secondUserDistinctId },
            ])
            const state: PersonMergeService = personMergeService({}, hub)
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
            const persons = sortPersons(await fetchPostgresPersonsH())
            expect(persons).toEqual(
                expect.arrayContaining([
                    expect.objectContaining({
                        id: expect.any(String),
                        uuid: firstUserUuid,
                        properties: {},
                        created_at: timestamp,
                        version: 0,
                        is_identified: false,
                    }),
                    expect.objectContaining({
                        id: expect.any(String),
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
            await createPerson(hub, timestamp, {}, {}, {}, teamId, null, false, firstUserUuid, [
                { distinctId: firstUserDistinctId },
            ])
            await createPerson(hub, timestamp, {}, {}, {}, teamId, null, false, secondUserUuid, [
                { distinctId: secondUserDistinctId },
            ])

            const state: PersonMergeService = personMergeService(
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
            const persons = sortPersons(await fetchPostgresPersonsH())
            expect(persons).toEqual(
                expect.arrayContaining([
                    expect.objectContaining({
                        id: expect.any(String),
                        uuid: firstUserUuid,
                        properties: {},
                        created_at: timestamp,
                        version: 0,
                        is_identified: false,
                    }),
                    expect.objectContaining({
                        id: expect.any(String),
                        uuid: secondUserUuid,
                        properties: {},
                        created_at: timestamp,
                        version: 0,
                        is_identified: false,
                    }),
                ])
            )
        })
    })
})
