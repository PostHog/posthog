import LibrdKafkaError from 'node-rdkafka-acosom/lib/error'
import { Pool } from 'pg'

import { defaultConfig } from '../../../../src/config/config'
import { eachBatch } from '../../../../src/main/ingestion-queues/session-recording/session-recordings-consumer'
import { TeamManager } from '../../../../src/worker/ingestion/team-manager'
import { createOrganization, createTeam } from '../../../helpers/sql'

describe('session-recordings-consumer', () => {
    const producer = {
        produce: jest.fn(),
        flush: jest.fn(),
    } as any
    let postgres: Pool
    let teamManager: TeamManager
    let eachBachWithDependencies: any

    beforeEach(() => {
        postgres = new Pool({ connectionString: defaultConfig.DATABASE_URL })
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

        // Should have send to the DLQ.
        expect(producer.produce).toHaveBeenCalledTimes(1)
    })
})
