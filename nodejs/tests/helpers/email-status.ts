import { buildEmailStatusRow } from '~/cdp/services/messaging/email-status.service'
import { KAFKA_EMAIL_STATUS } from '~/common/config/kafka-topics'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { UUIDT } from '~/common/utils/utils'
import { Clickhouse } from '~/tests/helpers/clickhouse'
import { waitForExpect } from '~/tests/helpers/expectations'
import { ensureKafkaTopics } from '~/tests/helpers/kafka'

const ActualKafkaProducerWrapper: typeof KafkaProducerWrapper =
    jest.requireActual('~/common/kafka/producer').KafkaProducerWrapper

export interface StoredEmailStatus {
    status: string
    reason: string
}

/**
 * Probe email_status until a row lands, proving the ClickHouse Kafka engine's consumer has attached. Its
 * `auto.offset.reset=latest` drops rows produced before attach.
 */
export const waitForEmailStatusMvReady = async (clickhouse: Clickhouse): Promise<void> => {
    await ensureKafkaTopics([KAFKA_EMAIL_STATUS])
    const producer = await ActualKafkaProducerWrapper.create(undefined)
    const probeTeamId = -999_999
    try {
        await waitForExpect(async () => {
            const probe = buildEmailStatusRow({
                teamId: probeTeamId,
                messageId: new UUIDT().toString(),
                status: 'queued',
            })
            await producer.queueMessages({
                topic: KAFKA_EMAIL_STATUS,
                messages: [{ key: probe.message_id, value: JSON.stringify(probe) }],
            })
            await producer.flush()

            const result = await clickhouse.query<{ c: number }>(
                `SELECT count() AS c FROM email_status WHERE team_id = ${probeTeamId}`
            )
            expect(Number(result[0]?.c ?? 0)).toBeGreaterThan(0)
        }, 30_000)
    } finally {
        await producer.disconnect()
    }
}

export const storedEmailStatus = async (
    clickhouse: Clickhouse,
    teamId: number,
    messageId: string
): Promise<StoredEmailStatus | undefined> => {
    const rows = await clickhouse.query<StoredEmailStatus>(
        `SELECT status, reason FROM email_status FINAL WHERE team_id = ${teamId} AND message_id = '${messageId}'`
    )
    return rows[0]
}
