import { KafkaJSError } from 'kafkajs'
import { Pool } from 'pg'

import { defaultConfig } from '../../../src/config/config'
import { eachBatch } from '../../../src/main/ingestion-queues/session-recordings-consumer'
import { DependencyUnavailableError } from '../../../src/utils/db/error'
import { TeamManager } from '../../../src/worker/ingestion/team-manager'
import { createOrganization, createTeam } from '../../helpers/sql'

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
        eachBachWithDependencies = eachBatch({ groupId: 'asdf', producer, teamManager })
    })

    afterEach(() => {
        jest.clearAllMocks()
    })

    test('eachBatch throws on recoverable KafkaJS errors', async () => {
        const organizationId = await createOrganization(postgres)
        const teamId = await createTeam(postgres, organizationId)
        const error = new KafkaJSError('test', { retriable: true })
        producer.produce.mockImplementation((topic, partition, message, key, timestamp, cb) => cb(error))
        producer.flush.mockImplementation((timeout, cb) => cb(error))
        await expect(
            eachBachWithDependencies({
                batch: {
                    topic: 'test',
                    messages: [
                        {
                            key: 'test',
                            value: JSON.stringify({ team_id: teamId, data: JSON.stringify({ event: '$snapshot' }) }),
                        },
                    ],
                } as any,
                heartbeat: jest.fn(),
            })
        ).rejects.toEqual(new DependencyUnavailableError('KafkaJSError', 'Kafka', error))
    })

    test('eachBatch emits to DLQ and returns on unrecoverable KafkaJS errors', async () => {
        const error = new KafkaJSError('test', { retriable: false })
        producer.produce.mockRejectedValue(error)
        await eachBachWithDependencies({
            batch: {
                topic: 'test',
                messages: [
                    {
                        key: 'test',
                        value: JSON.stringify({ data: { event: '$snapshot' } }),
                    },
                ],
            } as any,
            heartbeat: jest.fn(),
        })
    })
})
