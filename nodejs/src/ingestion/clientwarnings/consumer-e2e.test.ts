import { Clickhouse } from '~/../tests/helpers/clickhouse'
import { waitForExpect } from '~/../tests/helpers/expectations'
import {
    EventBuilder,
    createKafkaMessages,
    createTestWithTeamIngester,
    fetchIngestionWarnings,
    waitForClickHouseKafkaConsumer,
    waitForKafkaMessages,
} from '~/../tests/helpers/ingestion-e2e'
import { createTestIngestionOutputs } from '~/../tests/helpers/ingestion-outputs'
import { resetKafka } from '~/../tests/helpers/kafka'
import { resetTestDatabase } from '~/../tests/helpers/sql'

import { createClientWarningsConsumer } from './consumer'

jest.mock('~/utils/token-bucket', () => {
    const mockConsume = jest.fn().mockReturnValue(true)
    return {
        IngestionWarningLimiter: {
            consume: mockConsume,
        },
    }
})

jest.mock('../../utils/logger')

describe('ClientWarnings Consumer E2E', () => {
    const testWithTeamIngester = createTestWithTeamIngester({}, (hub, kafkaProducer) => {
        const outputs = createTestIngestionOutputs(kafkaProducer)
        return createClientWarningsConsumer(hub, {
            outputs,
            teamManager: hub.teamManager,
            postgres: hub.postgres,
            redisPool: hub.redisPool,
            staticDropEventTokens: [],
        })
    })
    let clickhouse: Clickhouse

    beforeAll(async () => {
        clickhouse = Clickhouse.create()
        await resetKafka()
        await resetTestDatabase()
        await clickhouse.resetTestDatabase()
        await waitForClickHouseKafkaConsumer(clickhouse)
        process.env.SITE_URL = 'https://example.com'
    })

    afterAll(async () => {
        await resetTestDatabase()
        await clickhouse.resetTestDatabase()
        clickhouse.close()
    })

    testWithTeamIngester(
        'should handle $$client_ingestion_warning events',
        {},
        async ({ hub, team, kafkaProducer, ingester, token }) => {
            const events = [
                new EventBuilder(team)
                    .withEvent('$$client_ingestion_warning')
                    .withProperties({ $$client_ingestion_warning_message: 'test message' })
                    .build(),
            ]

            const { backgroundTask } = await ingester.handleKafkaBatch(createKafkaMessages(events, token))
            await backgroundTask

            await waitForExpect(async () => {
                await waitForKafkaMessages(kafkaProducer)
                const warnings = await fetchIngestionWarnings(clickhouse, team.id)
                expect(warnings).toEqual([
                    expect.objectContaining({
                        type: 'client_ingestion_warning',
                        team_id: team.id,
                        details: expect.objectContaining({ message: 'test message' }),
                    }),
                ])
            })

            expect(hub).toBeDefined()
        }
    )
})
