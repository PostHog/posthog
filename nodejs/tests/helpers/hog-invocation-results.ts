import { DateTime } from 'luxon'

import { KAFKA_HOG_INVOCATION_RESULTS } from '~/common/config/kafka-topics'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { Clickhouse } from '~/tests/helpers/clickhouse'
import { waitForExpect } from '~/tests/helpers/expectations'

// The `~/common/kafka/producer` module is auto-mocked in these integration tests, so grab the
// real wrapper to actually push probe rows through Kafka.
const ActualKafkaProducerWrapper: typeof KafkaProducerWrapper =
    jest.requireActual('~/common/kafka/producer').KafkaProducerWrapper

/**
 * Probe the ClickHouse Kafka MV for the hog_invocation_results topic in particular. With
 * `auto.offset.reset=latest` on the engine's consumer, anything produced before the MV's
 * internal consumer has attached is silently dropped — so a seed run right after topic
 * (re)creation can lose rows and never satisfy a row-count poll. Send probe rows until one
 * lands in ClickHouse so we know the MV is live before the test produces real rows.
 */
export const waitForHogInvocationResultsMvReady = async (clickhouse: Clickhouse): Promise<void> => {
    const producer = await ActualKafkaProducerWrapper.create(undefined)
    const probeTeamId = -999_999
    try {
        await waitForExpect(async () => {
            await producer.queueMessages({
                topic: KAFKA_HOG_INVOCATION_RESULTS,
                messages: [
                    {
                        key: 'probe',
                        value: JSON.stringify({
                            team_id: probeTeamId,
                            function_kind: 'hog_function',
                            function_id: 'probe',
                            invocation_id: 'probe',
                            parent_run_id: '',
                            status: 'running',
                            attempts: 0,
                            is_retry: 0,
                            scheduled_at: DateTime.utc().toFormat("yyyy-MM-dd HH:mm:ss.SSS'000'"),
                            started_at: null,
                            finished_at: null,
                            duration_ms: null,
                            error_kind: '',
                            error_message: '',
                            event_uuid: '',
                            distinct_id: '',
                            person_id: '',
                            invocation_globals: '{}',
                            version: String(BigInt(Date.now()) * 1000n),
                            is_deleted: 0,
                        }),
                    },
                ],
            })
            await producer.flush()

            const result = await clickhouse.query<{ c: number }>(
                `SELECT count() AS c FROM hog_invocation_results WHERE team_id = ${probeTeamId}`
            )
            expect(Number(result[0]?.c ?? 0)).toBeGreaterThan(0)
        }, 30_000)
    } finally {
        await producer.disconnect()
    }
}
