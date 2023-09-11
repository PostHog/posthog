import { DateTime } from 'luxon'
import LibrdKafkaError from 'node-rdkafka/lib/error'

import { defaultConfig } from '../../../../src/config/config'
import { eachBatch } from '../../../../src/main/ingestion-queues/session-recording/session-recordings-consumer-v1'
import { now } from '../../../../src/main/ingestion-queues/session-recording/utils'
import { PostgresRouter } from '../../../../src/utils/db/postgres'
import { TeamManager } from '../../../../src/worker/ingestion/team-manager'
import { createOrganization, createTeam } from '../../../helpers/sql'

describe('session-recordings-consumer', () => {
    const producer = {
        produce: jest.fn(),
        flush: jest.fn(),
    } as any
    let postgres: PostgresRouter
    let teamManager: TeamManager
    let eachBachWithDependencies: any

    beforeEach(() => {
        postgres = new PostgresRouter(defaultConfig, undefined)
        teamManager = new TeamManager(postgres, {} as any)
        eachBachWithDependencies = eachBatch({ producer, teamManager })
    })

    afterEach(() => {
        jest.clearAllMocks()
    })

    test('eachBatch throws on recoverable Kafka errors', async () => {
        const organizationId = await createOrganization(postgres)
        const teamId = await createTeam(postgres, organizationId)
        const error = new LibrdKafkaError({ message: 'test', code: 1, errno: 1, origin: 'test', isRetriable: true })
        producer.produce.mockImplementation(
            (_topic: any, _partition: any, _message: any, _key: any, _timestamp: any, _headers: any, cb: any) =>
                cb(error)
        )
        producer.flush.mockImplementation((_timeout: any, cb: any) => cb(null))
        await expect(
            eachBachWithDependencies([
                {
                    key: 'test',
                    value: JSON.stringify({ team_id: teamId, data: JSON.stringify({ event: '$snapshot' }) }),
                },
            ])
        ).rejects.toEqual(error)
    })

    test('eachBatch emits to DLQ and returns on unrecoverable KafkaJS errors', async () => {
        const organizationId = await createOrganization(postgres)
        const teamId = await createTeam(postgres, organizationId)
        const error = new LibrdKafkaError({ message: 'test', code: 1, errno: 1, origin: 'test', isRetriable: false })
        producer.produce.mockImplementation(
            (_topic: any, _partition: any, _message: any, _key: any, _timestamp: any, _headers: any, cb: any) =>
                cb(error)
        )
        producer.flush.mockImplementation((_timeout: any, cb: any) => cb(null))
        await eachBachWithDependencies([
            {
                key: 'test',
                value: JSON.stringify({ team_id: teamId, data: JSON.stringify({ event: '$snapshot' }) }),
            },
        ])

        // Should have sent to the DLQ.
        expect(producer.produce).toHaveBeenCalledTimes(1)
    })

    test('eachBatch emits to only one topic', async () => {
        const organizationId = await createOrganization(postgres)
        const teamId = await createTeam(postgres, organizationId)

        await eachBachWithDependencies([
            {
                key: 'test',
                value: JSON.stringify({ team_id: teamId, data: JSON.stringify({ event: '$snapshot' }) }),
                timestamp: 123,
            },
        ])

        expect(producer.produce).toHaveBeenCalledTimes(1)
    })

    test('eachBatch can emit to two topics', async () => {
        const organizationId = await createOrganization(postgres)
        const teamId = await createTeam(postgres, organizationId)

        const eachBachWithDependencies: any = eachBatch({ producer, teamManager })

        await eachBachWithDependencies([
            {
                key: 'test',
                value: JSON.stringify({
                    team_id: teamId,
                    data: JSON.stringify({
                        event: '$snapshot',
                        properties: { $snapshot_data: { events_summary: [{ timestamp: now() }] } },
                    }),
                }),
                timestamp: 123,
            },
        ])

        expect(producer.produce).toHaveBeenCalledTimes(2)
    })

    test('eachBatch does not emit replay event if set to other consumer', async () => {
        const organizationId = await createOrganization(postgres)
        const teamId = await createTeam(postgres, organizationId)

        const eachBachWithDependencies: any = eachBatch({ producer, teamManager })

        await eachBachWithDependencies([
            {
                key: 'test',
                value: JSON.stringify({
                    team_id: teamId,
                    data: JSON.stringify({
                        event: '$snapshot',
                        properties: {
                            $snapshot_data: { events_summary: [{ timestamp: now() }] },
                            $snapshot_consumer: 'v2',
                        },
                    }),
                }),
                timestamp: 123,
            },
        ])

        expect(producer.produce).toHaveBeenCalledTimes(1)
    })

    test('eachBatch does not emit a replay record that is more than a month in the future', async () => {
        const organizationId = await createOrganization(postgres)
        const teamId = await createTeam(postgres, organizationId)

        const eachBachWithDependencies: any = eachBatch({ producer, teamManager })

        const aMonthInFuture = DateTime.now().plus({ months: 1 }).toMillis()

        await eachBachWithDependencies([
            {
                key: 'test',
                value: JSON.stringify({
                    team_id: teamId,
                    data: JSON.stringify({
                        event: '$snapshot',
                        properties: { $snapshot_data: { events_summary: [{ timestamp: aMonthInFuture }] } },
                    }),
                }),
                timestamp: 123,
            },
        ])

        expect(producer.produce).toHaveBeenCalledTimes(1)
    })

    test('eachBatch does not emit a replay record that is more than a month in the past', async () => {
        const organizationId = await createOrganization(postgres)
        const teamId = await createTeam(postgres, organizationId)

        const eachBachWithDependencies: any = eachBatch({ producer, teamManager })

        const aMonthInFuture = DateTime.now().minus({ months: 1 }).toMillis()

        await eachBachWithDependencies([
            {
                key: 'test',
                value: JSON.stringify({
                    team_id: teamId,
                    data: JSON.stringify({
                        event: '$snapshot',
                        properties: { $snapshot_data: { events_summary: [{ timestamp: aMonthInFuture }] } },
                    }),
                }),
                timestamp: 123,
            },
        ])

        expect(producer.produce).toHaveBeenCalledTimes(1)
    })
})
