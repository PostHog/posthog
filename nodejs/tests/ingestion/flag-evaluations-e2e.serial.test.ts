// Serial: resets the shared test database.
// Pins the full flag-evaluations shadow-write path — config → fork step → output
// registration → Kafka topic → ClickHouse Kafka engine → MV → flag_evaluations
// table — which no unit test can: a topic-key typo, a row column ClickHouse can't
// parse (silently eaten by kafka_skip_broken_messages), or a broken MV projection
// all produce "row queued but never lands".
import { createHogTransformerService } from '~/cdp/hog-transformations/hog-transformer.service'
import { KAFKA_CLICKHOUSE_FLAG_EVALUATIONS } from '~/common/config/kafka-topics'
import { ClickhouseGroupRepository } from '~/common/groups/repositories/clickhouse-group-repository'
import { parseJSON } from '~/common/utils/json-parse'
import { createFlagEvaluationsService } from '~/ingestion/common/flag-evaluations/flag-evaluations-service'
import { getDefaultIngestionConsumerConfig, getDefaultIngestionOutputsConfig } from '~/ingestion/config'
import { IngestionConsumer } from '~/ingestion/ingestion-consumer'
import { Clickhouse } from '~/tests/helpers/clickhouse'
import { waitForExpect } from '~/tests/helpers/expectations'
import {
    EventBuilder,
    createKafkaMessages,
    createTestWithTeamIngester,
    fetchEvents,
    fetchFlagEvaluations,
    waitForClickHouseKafkaConsumer,
    waitForKafkaMessages,
} from '~/tests/helpers/ingestion-e2e'
import { createTestIngestionOutputs, createTestMonitoringOutputs } from '~/tests/helpers/ingestion-outputs'
import { TEST_KAFKA_TOPICS, ensureKafkaTopics } from '~/tests/helpers/kafka'
import { resetTestDatabase } from '~/tests/helpers/sql'

jest.mock('~/common/utils/logger')

describe('Flag evaluations shadow-routing E2E', () => {
    const testWithTeamIngester = createTestWithTeamIngester({}, (infra, kafkaProducer) => {
        const outputs = createTestIngestionOutputs(kafkaProducer)
        return new IngestionConsumer(infra.config, {
            ...infra,
            hogTransformer: createHogTransformerService(infra.config, {
                ...infra,
                monitoringOutputs: createTestMonitoringOutputs(kafkaProducer),
            }),
            outputs,
            clickhouseGroupRepository: new ClickhouseGroupRepository(outputs),
        })
    })

    let clickhouse: Clickhouse

    beforeAll(async () => {
        clickhouse = Clickhouse.create()
        await ensureKafkaTopics(TEST_KAFKA_TOPICS)
        await resetTestDatabase()
        await clickhouse.resetTestDatabase()
        await waitForClickHouseKafkaConsumer(clickhouse)
    })

    afterAll(async () => {
        await resetTestDatabase()
        await clickhouse.resetTestDatabase()
        clickhouse.close()
    })

    testWithTeamIngester(
        'dual_write mode: a $feature_flag_called event lands in both flag_evaluations and events',
        {
            pluginServerConfig: {
                INGESTION_FLAG_EVALUATIONS_MODE: 'dual_write',
                INGESTION_FLAG_EVALUATIONS_TEAMS: '*',
                INGESTION_OUTPUT_FLAG_EVALUATIONS_TOPIC: KAFKA_CLICKHOUSE_FLAG_EVALUATIONS,
            },
        },
        async ({ ingester, team, kafkaProducer, token }) => {
            const event = new EventBuilder(team)
                .withEvent('$feature_flag_called')
                .withProperties({
                    $feature_flag: 'my-flag',
                    $feature_flag_response: true,
                })
                .build()

            await ingester.handleKafkaBatch(createKafkaMessages([event], token))
            await waitForKafkaMessages(kafkaProducer)

            const flagEvaluations = await waitForExpect(async () => {
                const rows = await fetchFlagEvaluations(clickhouse, team.id)
                expect(rows.length).toBe(1)
                return rows
            }, 30_000)

            // The two rows do not necessarily arrive on the same Kafka flush, and the
            // events row is usually the later of the two, so this read is polled too.
            const events = await waitForExpect(async () => {
                const rows = await fetchEvents(clickhouse, team.id)
                expect(rows.length).toBe(1)
                return rows
            }, 30_000)
            expect(events[0].event).toBe('$feature_flag_called')
            expect(events[0].properties.$feature_flag).toBe('my-flag')

            expect(flagEvaluations[0].event).toBe('$feature_flag_called')
            expect(flagEvaluations[0].uuid).toBe(event.uuid)
            expect(parseJSON(flagEvaluations[0].properties).$feature_flag).toBe('my-flag')
            // The shard materializes these out of properties; reading them
            // through the flag_evaluations proxy proves that wiring.
            expect(flagEvaluations[0].flag_key).toBe('my-flag')
            expect(flagEvaluations[0].response).toBe('true')
            // person_id must match what the events table stamped for the same
            // event — the parity per-flag uniques depend on.
            expect(flagEvaluations[0].person_id).not.toBe('00000000-0000-0000-0000-000000000000')
            expect(flagEvaluations[0].person_id).toBe(events[0].person_id)
            // The producer omits inserted_at; the MV fallback must fill it.
            expect(flagEvaluations[0].inserted_at).not.toMatch(/^1970/)
        }
    )

    it('ships disabled by default', () => {
        // The only thing the round trip above would add for the disabled case:
        // that nothing flipped the fleet default. createFlagEvaluationsService
        // returning undefined is what keeps the step out of the pipeline.
        const config = { ...getDefaultIngestionConsumerConfig(), ...getDefaultIngestionOutputsConfig() }

        expect(config.INGESTION_FLAG_EVALUATIONS_MODE).toBe('disabled')
        expect(createFlagEvaluationsService(config)).toBeUndefined()
    })
})
