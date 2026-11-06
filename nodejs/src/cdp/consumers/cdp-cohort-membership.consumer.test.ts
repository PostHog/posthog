import { Message } from 'node-rdkafka'

import { KAFKA_COHORT_MEMBERSHIP_CHANGED } from '~/common/config/kafka-topics'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresUse } from '~/common/utils/db/postgres'
import { UUIDT } from '~/common/utils/utils'

import { createCdpConsumerDeps } from '../../../tests/helpers/cdp'
import { Hub } from '../../types'
import { createCohortMembershipEvent, createCohortMembershipEvents, createKafkaMessage } from '../_tests/fixtures'
import { CdpCohortMembershipConsumer } from './cdp-cohort-membership.consumer'

describe('CdpCohortMembershipConsumer', () => {
    let hub: Hub
    let consumer: CdpCohortMembershipConsumer
    // Never started: it exercises the flag-on persistence paths directly, without a marker
    // consumer connection.
    let sweepConsumer: CdpCohortMembershipConsumer
    let teamId: number
    let cluster: string
    let personId1: string
    let personId2: string
    let personId3: string

    beforeEach(async () => {
        hub = await createHub()
        const deps = createCdpConsumerDeps(hub)
        consumer = new CdpCohortMembershipConsumer(hub, deps)
        sweepConsumer = new CdpCohortMembershipConsumer(
            { ...hub, COHORT_MEMBERSHIP_VERSION_WRITES_ENABLED: true, COHORT_MEMBERSHIP_SWEEP_ENABLED: true },
            deps
        )
        teamId = Number.parseInt(new UUIDT().toString().replaceAll('-', '').slice(-7), 16)
        // Progress rows key on (cluster, partition) and nothing truncates between tests, so a
        // unique cluster isolates each test from parallel workers and from prior runs.
        cluster = `test-cluster-${new UUIDT().toString()}`
        consumer['membershipCluster'] = cluster
        sweepConsumer['membershipCluster'] = cluster
        personId1 = new UUIDT().toString()
        personId2 = new UUIDT().toString()
        personId3 = new UUIDT().toString()
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    it('should refuse to construct a sweeping consumer whose own write path skips versions', () => {
        // The flag ordering (version writes on first and off last, sweep on last and off first)
        // is enforced nowhere else: a pod that swept while writing without versions would delete
        // rows its own upserts left carrying a stale stamp.
        expect(
            () =>
                new CdpCohortMembershipConsumer(
                    { ...hub, COHORT_MEMBERSHIP_VERSION_WRITES_ENABLED: false, COHORT_MEMBERSHIP_SWEEP_ENABLED: true },
                    createCdpConsumerDeps(hub)
                )
        ).toThrow('COHORT_MEMBERSHIP_SWEEP_ENABLED requires COHORT_MEMBERSHIP_VERSION_WRITES_ENABLED')
    })

    describe('end-to-end cohort membership processing', () => {
        const readProgress = async (): Promise<Record<string, any>[]> => {
            const result = await hub.postgres.query(
                PostgresUse.BEHAVIORAL_COHORTS_RW,
                'SELECT partition, next_offset FROM cohort_membership_consumer_progress WHERE cluster = $1 ORDER BY partition',
                [cluster],
                'testQuery'
            )
            return result.rows
        }

        it('should process entered and left events and write to PostgreSQL correctly', async () => {
            const testEvents = createCohortMembershipEvents([
                {
                    person_id: personId1,
                    cohort_id: 456,
                    team_id: teamId,
                    status: 'entered',
                },
                {
                    person_id: personId2,
                    cohort_id: 456,
                    team_id: teamId,
                    status: 'entered',
                },
                {
                    person_id: personId3,
                    cohort_id: 457,
                    team_id: teamId,
                    status: 'left',
                },
            ])

            const messages = testEvents.map((event, index) =>
                createKafkaMessage(event, { topic: KAFKA_COHORT_MEMBERSHIP_CHANGED, offset: index })
            )

            const cohortMembershipChanges = consumer['_parseAndValidateBatch'](messages)
            await consumer['persistCohortMembershipChanges'](cohortMembershipChanges)

            const result = await hub.postgres.query(
                PostgresUse.BEHAVIORAL_COHORTS_RW,
                'SELECT * FROM cohort_membership WHERE team_id = $1 ORDER BY person_id, cohort_id',
                [teamId],
                'testQuery'
            )

            expect(result.rows).toHaveLength(3)

            expect(result.rows[0]).toMatchObject({
                team_id: String(teamId),
                cohort_id: '456',
                person_id: personId1,
                in_cohort: true,
            })

            expect(result.rows[1]).toMatchObject({
                team_id: String(teamId),
                cohort_id: '456',
                person_id: personId2,
                in_cohort: true,
            })

            expect(result.rows[2]).toMatchObject({
                team_id: String(teamId),
                cohort_id: '457',
                person_id: personId3,
                in_cohort: false,
            })
        })

        it('should handle complete person lifecycle: enter -> leave -> re-enter cohort', async () => {
            // Step 1: Person enters the cohort
            const enterEvent = createCohortMembershipEvent({
                person_id: personId1,
                cohort_id: 456,
                team_id: teamId,
                status: 'entered',
            })

            const enterMessages = [
                createKafkaMessage(enterEvent, { topic: KAFKA_COHORT_MEMBERSHIP_CHANGED, offset: 0 }),
            ]
            const enterChanges = consumer['_parseAndValidateBatch'](enterMessages)
            await consumer['persistCohortMembershipChanges'](enterChanges)

            let result = await hub.postgres.query(
                PostgresUse.BEHAVIORAL_COHORTS_RW,
                'SELECT * FROM cohort_membership WHERE team_id = $1 AND person_id = $2 AND cohort_id = $3',
                [teamId, personId1, 456],
                'testQuery'
            )

            expect(result.rows[0].in_cohort).toBe(true)
            const firstTimestamp = result.rows[0].last_updated

            await new Promise((resolve) => setTimeout(resolve, 10))

            // Step 2: Person leaves the cohort
            const leaveEvent = createCohortMembershipEvent({
                person_id: personId1,
                cohort_id: 456,
                team_id: teamId,
                status: 'left',
            })

            const leaveMessages = [
                createKafkaMessage(leaveEvent, { topic: KAFKA_COHORT_MEMBERSHIP_CHANGED, offset: 1 }),
            ]
            const leaveChanges = consumer['_parseAndValidateBatch'](leaveMessages)
            await consumer['persistCohortMembershipChanges'](leaveChanges)

            result = await hub.postgres.query(
                PostgresUse.BEHAVIORAL_COHORTS_RW,
                'SELECT * FROM cohort_membership WHERE team_id = $1 AND person_id = $2 AND cohort_id = $3',
                [teamId, personId1, 456],
                'testQuery'
            )

            expect(result.rows).toHaveLength(1)
            expect(result.rows[0].in_cohort).toBe(false)
            const secondTimestamp = result.rows[0].last_updated
            expect(new Date(secondTimestamp).getTime()).toBeGreaterThan(new Date(firstTimestamp).getTime())

            await new Promise((resolve) => setTimeout(resolve, 10))

            // Step 3: Person re-enters the cohort
            const reEnterEvent = createCohortMembershipEvent({
                person_id: personId1,
                cohort_id: 456,
                team_id: teamId,
                status: 'entered',
            })

            const reEnterMessages = [
                createKafkaMessage(reEnterEvent, { topic: KAFKA_COHORT_MEMBERSHIP_CHANGED, offset: 2 }),
            ]
            const reEnterChanges = consumer['_parseAndValidateBatch'](reEnterMessages)
            await consumer['persistCohortMembershipChanges'](reEnterChanges)

            result = await hub.postgres.query(
                PostgresUse.BEHAVIORAL_COHORTS_RW,
                'SELECT * FROM cohort_membership WHERE team_id = $1 AND person_id = $2 AND cohort_id = $3',
                [teamId, personId1, 456],
                'testQuery'
            )

            expect(result.rows).toHaveLength(1)
            expect(result.rows[0].in_cohort).toBe(true)
            const thirdTimestamp = result.rows[0].last_updated
            expect(new Date(thirdTimestamp).getTime()).toBeGreaterThan(new Date(secondTimestamp).getTime())
        })

        it.each([
            ['keeping last in Kafka order for equal versions', false, {}, {}, false],
            // The version-aware pick only exists on the version-writes path. With the flag off
            // there is no SQL guard for it to agree with, so Kafka order must win even when the
            // stamps run backwards: anything else would change the write shape on deploy, before
            // any flag flips.
            [
                'keeping last in Kafka order even for a lower version while version writes are off',
                false,
                { last_updated: '2026-05-26 13:00:00.000000' },
                { last_updated: '2026-05-26 12:00:00.000000' },
                false,
            ],
            // The SQL guard only ever sees the batch's surviving entry, so the in-memory pick has
            // to agree with last-writer-wins: a newer version beats a later offset.
            [
                'keeping the highest version regardless of order with version writes on',
                true,
                { last_updated: '2026-05-26 13:00:00.000000' },
                { last_updated: '2026-05-26 12:00:00.000000' },
                true,
            ],
            // A versionless change applies unconditionally in SQL, so it also has to win the
            // in-batch pick, even against a versioned entry earlier in Kafka order.
            [
                'keeping a later versionless change over an earlier versioned one with version writes on',
                true,
                { last_updated: '2026-05-26 13:00:00.000000' },
                {},
                false,
            ],
        ])(
            'should deduplicate batch entries for the same (team_id, cohort_id, person_id), %s',
            async (_label, withVersionWrites, firstTags, secondTags, expectedInCohort) => {
                const target = withVersionWrites ? sweepConsumer : consumer
                const testEvents = createCohortMembershipEvents([
                    {
                        person_id: personId1,
                        cohort_id: 456,
                        team_id: teamId,
                        status: 'entered',
                        ...firstTags,
                    },
                    {
                        person_id: personId1,
                        cohort_id: 456,
                        team_id: teamId,
                        status: 'left',
                        ...secondTags,
                    },
                ])

                const messages = testEvents.map((event, index) =>
                    createKafkaMessage(event, { topic: KAFKA_COHORT_MEMBERSHIP_CHANGED, offset: index })
                )

                const cohortMembershipChanges = target['_parseAndValidateBatch'](messages)
                await target['persistCohortMembershipChanges'](cohortMembershipChanges)

                const result = await hub.postgres.query(
                    PostgresUse.BEHAVIORAL_COHORTS_RW,
                    'SELECT * FROM cohort_membership WHERE team_id = $1 AND person_id = $2 AND cohort_id = $3',
                    [teamId, personId1, 456],
                    'testQuery'
                )

                expect(result.rows).toHaveLength(1)
                expect(result.rows[0].in_cohort).toBe(expectedInCohort)
            }
        )

        it.each([
            ['seed' as const, new UUIDT().toString()],
            ['reconcile' as const, new UUIDT().toString()],
        ])('should carry origin=%s and run_id through parsing', (origin, runId) => {
            const message = createKafkaMessage(
                createCohortMembershipEvent({
                    person_id: personId1,
                    cohort_id: 456,
                    team_id: teamId,
                    origin,
                    run_id: runId,
                }),
                { topic: KAFKA_COHORT_MEMBERSHIP_CHANGED, offset: 0 }
            )

            const [change] = consumer['_parseAndValidateBatch']([message])

            expect(change.origin).toBe(origin)
            expect(change.run_id).toBe(runId)
        })

        it('should carry an unknown origin through parsing without rejecting the batch', () => {
            const runId = new UUIDT().toString()
            const message = createKafkaMessage(
                createCohortMembershipEvent({
                    person_id: personId1,
                    cohort_id: 456,
                    team_id: teamId,
                    status: 'entered',
                    origin: 'snapshot',
                    run_id: runId,
                }),
                { topic: KAFKA_COHORT_MEMBERSHIP_CHANGED, offset: 0 }
            )

            const [change] = consumer['_parseAndValidateBatch']([message])

            expect(change.origin).toBe('snapshot')
            expect(change.run_id).toBe(runId)
            expect(change).toMatchObject({
                person_id: personId1,
                cohort_id: 456,
                team_id: teamId,
                status: 'entered',
            })
        })

        // The producer's format, which is fixed-width so that string order is chronological.
        const OLDER_VERSION = '2026-05-26 12:00:00.000000'
        const VERSION = '2026-05-26 12:34:56.789123'
        const NEWER_VERSION = '2026-05-26 13:00:00.000000'

        const readVersion = async (cohortId: number): Promise<string | null> => {
            const result = await hub.postgres.query(
                PostgresUse.BEHAVIORAL_COHORTS_RW,
                `SELECT in_cohort, to_char(version, 'YYYY-MM-DD HH24:MI:SS.US') AS version
                 FROM cohort_membership WHERE team_id = $1 AND person_id = $2 AND cohort_id = $3`,
                [teamId, personId1, cohortId],
                'testQuery'
            )
            return result.rows[0].version
        }

        it.each([
            ['a live transition', {}],
            ['a seed row', { origin: 'seed' as const, run_id: new UUIDT().toString() }],
            ['a reconcile row', { origin: 'reconcile' as const, run_id: new UUIDT().toString() }],
        ])('should persist the message version for %s', async (_label, tags) => {
            const message = createKafkaMessage(
                createCohortMembershipEvent({
                    person_id: personId1,
                    cohort_id: 456,
                    team_id: teamId,
                    last_updated: VERSION,
                    ...tags,
                }),
                { topic: KAFKA_COHORT_MEMBERSHIP_CHANGED, offset: 0 }
            )

            await sweepConsumer['handleBatch']([message])

            expect(await readVersion(456)).toEqual(VERSION)
        })

        it.each([
            ['an older version is rejected', VERSION, OLDER_VERSION, true, VERSION],
            ['an equal version is applied', VERSION, VERSION, false, VERSION],
            ['a newer version is applied', VERSION, NEWER_VERSION, false, NEWER_VERSION],
            ['any version beats a versionless row', undefined, OLDER_VERSION, false, OLDER_VERSION],
            // A change that lost its version (sanitized off-format stamp) is still a membership
            // transition: it must apply while leaving the row's stamp in place, instead of losing
            // to every stamped row and no-opping.
            ['a versionless change applies without moving the version', VERSION, undefined, false, VERSION],
        ])(
            'should apply last-writer-wins on replay: %s',
            async (_label, storedVersion, incomingVersion, expectedInCohort, expectedVersion) => {
                await sweepConsumer['handleBatch']([
                    createKafkaMessage(
                        createCohortMembershipEvent({
                            person_id: personId1,
                            cohort_id: 456,
                            team_id: teamId,
                            status: 'entered',
                            last_updated: storedVersion,
                        }),
                        { topic: KAFKA_COHORT_MEMBERSHIP_CHANGED, offset: 0 }
                    ),
                ])

                await sweepConsumer['handleBatch']([
                    createKafkaMessage(
                        createCohortMembershipEvent({
                            person_id: personId1,
                            cohort_id: 456,
                            team_id: teamId,
                            status: 'left',
                            last_updated: incomingVersion,
                        }),
                        { topic: KAFKA_COHORT_MEMBERSHIP_CHANGED, offset: 1 }
                    ),
                ])

                const result = await hub.postgres.query(
                    PostgresUse.BEHAVIORAL_COHORTS_RW,
                    `SELECT in_cohort, to_char(version, 'YYYY-MM-DD HH24:MI:SS.US') AS version
                     FROM cohort_membership WHERE team_id = $1 AND person_id = $2 AND cohort_id = 456`,
                    [teamId, personId1],
                    'testQuery'
                )

                expect(result.rows[0].in_cohort).toBe(expectedInCohort)
                expect(result.rows[0].version).toEqual(expectedVersion)
            }
        )

        it('should track the oldest version each reconcile run asserted, across batches', async () => {
            const runId = new UUIDT().toString()
            const reconcileRow = (personId: string, lastUpdated: string) =>
                createKafkaMessage(
                    createCohortMembershipEvent({
                        person_id: personId,
                        cohort_id: 456,
                        team_id: teamId,
                        origin: 'reconcile',
                        run_id: runId,
                        last_updated: lastUpdated,
                    }),
                    { topic: KAFKA_COHORT_MEMBERSHIP_CHANGED, offset: 0 }
                )

            await sweepConsumer['handleBatch']([
                reconcileRow(personId1, NEWER_VERSION),
                reconcileRow(personId2, VERSION),
                // A live transition rides the same topic and must not count as an assertion.
                createKafkaMessage(
                    createCohortMembershipEvent({
                        person_id: personId3,
                        cohort_id: 456,
                        team_id: teamId,
                        last_updated: OLDER_VERSION,
                    }),
                    { topic: KAFKA_COHORT_MEMBERSHIP_CHANGED, offset: 0 }
                ),
            ])

            const readSweep = async () => {
                const result = await hub.postgres.query(
                    PostgresUse.BEHAVIORAL_COHORTS_RW,
                    `SELECT team_id, marker_bits, status, snapshot_rows,
                            to_char(min_snapshot_version, 'YYYY-MM-DD HH24:MI:SS.US') AS min_snapshot_version
                     FROM cohort_membership_sweeps WHERE run_id = $1 AND cohort_id = 456`,
                    [runId],
                    'testQuery'
                )
                return result.rows
            }

            expect(await readSweep()).toEqual([
                {
                    team_id: String(teamId),
                    marker_bits: '0',
                    status: 'collecting',
                    snapshot_rows: '2',
                    min_snapshot_version: VERSION,
                },
            ])

            await sweepConsumer['handleBatch']([reconcileRow(personId3, OLDER_VERSION)])

            expect(await readSweep()).toEqual([
                {
                    team_id: String(teamId),
                    marker_bits: '0',
                    status: 'collecting',
                    snapshot_rows: '3',
                    min_snapshot_version: OLDER_VERSION,
                },
            ])

            // A reconcile assertion that lost its version still applies to its row while keeping
            // the row's old stamp, so it has to collapse the run's minimum to the sentinel
            // (rendered as NULL by to_char): otherwise the run's own sweep would delete the
            // person it just asserted.
            await sweepConsumer['handleBatch']([
                createKafkaMessage(
                    createCohortMembershipEvent({
                        person_id: personId1,
                        cohort_id: 456,
                        team_id: teamId,
                        origin: 'reconcile',
                        run_id: runId,
                    }),
                    { topic: KAFKA_COHORT_MEMBERSHIP_CHANGED, offset: 0 }
                ),
            ])

            expect(await readSweep()).toEqual([
                {
                    team_id: String(teamId),
                    marker_bits: '0',
                    status: 'collecting',
                    snapshot_rows: '4',
                    min_snapshot_version: null,
                },
            ])
        })

        it('should advance consumer progress to the next offset without ever regressing it', async () => {
            const rowOnPartition = (partition: number, offset: number) =>
                createKafkaMessage(
                    createCohortMembershipEvent({ person_id: new UUIDT().toString(), team_id: teamId }),
                    {
                        topic: KAFKA_COHORT_MEMBERSHIP_CHANGED,
                        partition,
                        offset,
                    }
                )

            await sweepConsumer['handleBatch']([rowOnPartition(3, 10), rowOnPartition(3, 11), rowOnPartition(7, 5)])

            expect(await readProgress()).toEqual([
                { partition: 3, next_offset: '12' },
                { partition: 7, next_offset: '6' },
            ])

            // A rebalance can replay from an older committed offset; the gate must not walk back.
            await sweepConsumer['handleBatch']([rowOnPartition(3, 0)])

            expect(await readProgress()).toEqual([
                { partition: 3, next_offset: '12' },
                { partition: 7, next_offset: '6' },
            ])
        })

        it('should keep the pre-sweep write shape while version writes are off', async () => {
            // The migrations are a prerequisite of the version-writes flip, not of the deploy, so
            // a flag-off batch must not touch the version column or the sweep tables.
            const runId = new UUIDT().toString()
            const message = createKafkaMessage(
                createCohortMembershipEvent({
                    person_id: personId1,
                    cohort_id: 456,
                    team_id: teamId,
                    origin: 'reconcile',
                    run_id: runId,
                    last_updated: VERSION,
                }),
                { topic: KAFKA_COHORT_MEMBERSHIP_CHANGED, offset: 0 }
            )

            await consumer['handleBatch']([message])

            const membership = await hub.postgres.query(
                PostgresUse.BEHAVIORAL_COHORTS_RW,
                `SELECT in_cohort, version = '-infinity'::timestamp AS unversioned
                 FROM cohort_membership WHERE team_id = $1 AND person_id = $2`,
                [teamId, personId1],
                'testQuery'
            )
            expect(membership.rows).toEqual([{ in_cohort: true, unversioned: true }])

            const sweeps = await hub.postgres.query(
                PostgresUse.BEHAVIORAL_COHORTS_RW,
                'SELECT 1 FROM cohort_membership_sweeps WHERE run_id = $1',
                [runId],
                'testQuery'
            )
            expect(sweeps.rows).toHaveLength(0)
            expect(await readProgress()).toHaveLength(0)
        })

        it('should sanitize a version the producer contract does not allow instead of failing the batch', () => {
            const message = createKafkaMessage(
                createCohortMembershipEvent({
                    person_id: personId1,
                    cohort_id: 456,
                    team_id: teamId,
                    last_updated: '2026-05-26T12:34:56Z',
                }),
                { topic: KAFKA_COHORT_MEMBERSHIP_CHANGED, offset: 0 }
            )

            const [change] = sweepConsumer['_parseAndValidateBatch']([message])

            expect(change.last_updated).toBeUndefined()
        })

        it('should contain a marker batch failure instead of taking the consumer down', async () => {
            // The marker batch's offsets commit either way, and a throw would escape to the
            // consumer loop and stop membership ingestion with it.
            sweepConsumer['sweeper'] = {
                parseMarkers: () => {
                    throw new Error('marker path failure')
                },
            } as any

            await expect(sweepConsumer['handleMarkerBatch']([])).resolves.toBeUndefined()
        })

        it('should refuse to capture watermarks from a partial partition list', async () => {
            const stubConsumer = {
                getPartitionsForTopic: jest.fn(),
                queryWatermarkOffsets: jest.fn((_topic: string, partition: number) =>
                    Promise.resolve([0, 10 + partition])
                ),
            }
            sweepConsumer['kafkaConsumer'] = stubConsumer as any

            // With no progress rows for this cluster there is no floor to validate the metadata
            // against, so any truncated list would pass as the full set: capture fails closed.
            stubConsumer.getPartitionsForTopic.mockResolvedValue([{ id: 0 }, { id: 1 }])
            await expect(sweepConsumer['captureMembershipWatermarks']()).rejects.toThrow(
                'No recorded consumer progress'
            )

            await sweepConsumer['upsertConsumerProgress'](PostgresUse.BEHAVIORAL_COHORTS_RW, [
                { partition: 0, nextOffset: 5 },
                { partition: 1, nextOffset: 7 },
                { partition: 2, nextOffset: 9 },
            ])

            // Three partitions have durable consumer progress on this cluster, so a broker
            // answering with two is a partial list, and capturing it would let the gate pass while
            // the missing partition still holds unconsumed snapshot rows.
            await expect(sweepConsumer['captureMembershipWatermarks']()).rejects.toThrow('Partial partition metadata')

            stubConsumer.getPartitionsForTopic.mockResolvedValue([{ id: 0 }, { id: 1 }, { id: 2 }])
            await expect(sweepConsumer['captureMembershipWatermarks']()).resolves.toEqual({
                0: 10,
                1: 11,
                2: 12,
            })
        })

        it('should refresh progress from committed offsets, skipping invalid ones and never regressing', async () => {
            const stubConsumer = { committedOffsets: jest.fn() }
            sweepConsumer['kafkaConsumer'] = stubConsumer as any

            // -1001 is rdkafka's "no committed offset" sentinel; another topic's offsets must not
            // leak into the membership gate.
            stubConsumer.committedOffsets.mockResolvedValue([
                { topic: KAFKA_COHORT_MEMBERSHIP_CHANGED, partition: 0, offset: 5 },
                { topic: KAFKA_COHORT_MEMBERSHIP_CHANGED, partition: 1, offset: -1001 },
                { topic: 'some_other_topic', partition: 2, offset: 9 },
            ])
            await sweepConsumer['refreshConsumerProgressFromCommittedOffsets']()

            expect(await readProgress()).toEqual([{ partition: 0, next_offset: '5' }])

            stubConsumer.committedOffsets.mockResolvedValue([
                { topic: KAFKA_COHORT_MEMBERSHIP_CHANGED, partition: 0, offset: 3 },
            ])
            await sweepConsumer['refreshConsumerProgressFromCommittedOffsets']()

            expect(await readProgress()).toEqual([{ partition: 0, next_offset: '5' }])
        })

        it('should reject entire batch when invalid messages are present', async () => {
            const validEvent = {
                person_id: personId1,
                cohort_id: 456,
                team_id: teamId,
                status: 'entered',
            }

            const messages: Message[] = [
                createKafkaMessage(validEvent, { topic: KAFKA_COHORT_MEMBERSHIP_CHANGED, offset: 0 }),
                {
                    value: Buffer.from('invalid json'),
                    topic: KAFKA_COHORT_MEMBERSHIP_CHANGED,
                    partition: 0,
                    offset: 1,
                    timestamp: Date.now(),
                    key: null,
                    size: 0,
                },
                createKafkaMessage({ person_id: 124 }, { topic: KAFKA_COHORT_MEMBERSHIP_CHANGED, offset: 2 }),
                {
                    value: null,
                    topic: KAFKA_COHORT_MEMBERSHIP_CHANGED,
                    partition: 0,
                    offset: 3,
                    timestamp: Date.now(),
                    key: null,
                    size: 0,
                },
            ]

            expect(() => consumer['_parseAndValidateBatch'](messages)).toThrow()

            const result = await hub.postgres.query(
                PostgresUse.BEHAVIORAL_COHORTS_RW,
                'SELECT * FROM cohort_membership WHERE team_id = $1',
                [teamId],
                'testQuery'
            )

            expect(result.rows).toHaveLength(0)
        })

        it('should not record consumer progress when the batch write fails', async () => {
            // A non-integer cohort_id passes schema validation but Postgres rejects it, so the
            // membership write fails while the progress write on its own would have succeeded.
            const message = createKafkaMessage(
                createCohortMembershipEvent({ person_id: personId1, team_id: teamId, cohort_id: 1.5 }),
                { topic: KAFKA_COHORT_MEMBERSHIP_CHANGED, partition: 9, offset: 42 }
            )

            await expect(sweepConsumer['handleBatch']([message])).rejects.toThrow()

            expect(await readProgress()).toHaveLength(0)
        })

        it('should not produce side effects when database insertion fails', async () => {
            const testEvents = createCohortMembershipEvents([
                {
                    person_id: personId1,
                    cohort_id: 456,
                    team_id: teamId,
                    status: 'entered',
                },
                {
                    person_id: personId2,
                    cohort_id: 456,
                    team_id: teamId,
                    status: 'entered',
                },
            ])

            const messages = testEvents.map((event, index) =>
                createKafkaMessage(event, { topic: KAFKA_COHORT_MEMBERSHIP_CHANGED, offset: index })
            )

            const cohortMembershipChanges = consumer['_parseAndValidateBatch'](messages)

            const originalQuery = hub.postgres.query.bind(hub.postgres)
            hub.postgres.query = jest.fn().mockRejectedValue(new Error('Database connection failed'))

            await expect(consumer['persistCohortMembershipChanges'](cohortMembershipChanges)).rejects.toThrow(
                'Database connection failed'
            )

            hub.postgres.query = originalQuery

            const result = await hub.postgres.query(
                PostgresUse.BEHAVIORAL_COHORTS_RW,
                'SELECT * FROM cohort_membership WHERE team_id = $1',
                [teamId],
                'testQuery'
            )
            expect(result.rows).toHaveLength(0)
        })
    })
})
