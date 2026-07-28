import { Message } from 'node-rdkafka'

import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { APP_METRICS_OUTPUT, DLQ_OUTPUT, INGESTION_WARNINGS_OUTPUT } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { SingleIngestionOutput } from '~/common/outputs/single-ingestion-output'
import { EventIngestionRestrictionManager } from '~/common/utils/event-ingestion-restrictions'
import { parseJSON } from '~/common/utils/json-parse'
import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { TeamManager } from '~/common/utils/team-manager'
import { UUIDT } from '~/common/utils/utils'
import { EventFilterManager } from '~/ingestion/common/event-filters'
import { createOkContext } from '~/ingestion/framework/helpers'
import { createTestTeam } from '~/tests/helpers/team'

import { ClientWarningsPipelineConfig, createClientWarningsPipeline } from './pipeline'

jest.mock('~/common/utils/logger', () => ({
    logger: { debug: jest.fn(), info: jest.fn(), warn: jest.fn(), error: jest.fn() },
}))

const WARNINGS_TOPIC = 'clickhouse_ingestion_warnings_test'
const DLQ_TOPIC = 'events_plugin_ingestion_dlq_test'

describe('ClientWarningsPipeline', () => {
    let mockKafkaProducer: jest.Mocked<KafkaProducerWrapper>
    let mockTeamManager: jest.Mocked<TeamManager>
    let mockEventIngestionRestrictionManager: jest.Mocked<EventIngestionRestrictionManager>
    let mockEventFilterManager: jest.Mocked<EventFilterManager>
    let promiseScheduler: PromiseScheduler
    let config: ClientWarningsPipelineConfig

    const team = createTestTeam({ id: 123, api_token: 'token-123' })

    const createMessage = (event: string, warningMessage = 'something broke'): Message => {
        const distinctId = 'user-1'
        const eventData = {
            event,
            distinct_id: distinctId,
            uuid: new UUIDT().toString(),
            timestamp: '2024-01-01T00:00:00Z',
            properties: { $$client_ingestion_warning_message: warningMessage },
        }
        return {
            value: Buffer.from(
                JSON.stringify({ token: team.api_token, data: JSON.stringify(eventData), ...eventData })
            ),
            headers: [
                { token: Buffer.from(team.api_token) },
                { distinct_id: Buffer.from(distinctId) },
                // Capture sets the event-name header; the allow-list reads it before the body is parsed.
                { event: Buffer.from(event) },
            ],
            topic: 'client_iwarnings_ingestion',
            partition: 0,
            offset: 0,
            size: 0,
            key: Buffer.from(distinctId),
        } as Message
    }

    const runPipeline = async (messages: Message[]): Promise<void> => {
        const pipeline = createClientWarningsPipeline<{ message: Message }, { message: Message }>(config)
        const batch = messages.map((message) => createOkContext({ message }, { message }))
        await pipeline.feed(batch)
        let result = await pipeline.next()
        while (result !== null) {
            // The pipeline handles its own side effects; none may leak to drivers.
            expect(result.sideEffects ?? []).toEqual([])
            result = await pipeline.next()
        }
        await promiseScheduler.waitForAll()
    }

    const warningsProduced = (): any[] =>
        mockKafkaProducer.queueMessages.mock.calls
            .map((call) => call[0])
            .filter((arg: any) => arg.topic === WARNINGS_TOPIC)
            .flatMap((arg: any) => arg.messages.map((m: { value: Buffer }) => parseJSON(m.value.toString())))

    const dlqProduced = (): any[] =>
        mockKafkaProducer.produce.mock.calls.map((call) => call[0]).filter((arg: any) => arg.topic === DLQ_TOPIC)

    beforeEach(() => {
        mockKafkaProducer = {
            produce: jest.fn().mockResolvedValue(undefined),
            queueMessages: jest.fn().mockResolvedValue(undefined),
            flush: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<KafkaProducerWrapper>

        mockTeamManager = {
            getTeamByToken: jest.fn().mockResolvedValue(team),
            getTeam: jest.fn().mockResolvedValue(team),
        } as unknown as jest.Mocked<TeamManager>

        mockEventIngestionRestrictionManager = {
            getAppliedRestrictions: jest.fn().mockReturnValue(new Set()),
            forceRefresh: jest.fn(),
        } as unknown as jest.Mocked<EventIngestionRestrictionManager>

        mockEventFilterManager = {
            getFilter: jest.fn().mockReturnValue(undefined),
        } as unknown as jest.Mocked<EventFilterManager>

        promiseScheduler = new PromiseScheduler()

        config = {
            outputs: new IngestionOutputs({
                [INGESTION_WARNINGS_OUTPUT]: new SingleIngestionOutput(
                    INGESTION_WARNINGS_OUTPUT,
                    WARNINGS_TOPIC,
                    mockKafkaProducer,
                    'test'
                ),
                [DLQ_OUTPUT]: new SingleIngestionOutput(DLQ_OUTPUT, DLQ_TOPIC, mockKafkaProducer, 'test'),
                [APP_METRICS_OUTPUT]: new SingleIngestionOutput(
                    APP_METRICS_OUTPUT,
                    'clickhouse_app_metrics2_test',
                    mockKafkaProducer,
                    'test'
                ),
            }),
            teamManager: mockTeamManager,
            eventIngestionRestrictionManager: mockEventIngestionRestrictionManager,
            eventFilterManager: mockEventFilterManager,
            promiseScheduler,
        }
    })

    it('emits a client_ingestion_warning for $$client_ingestion_warning events', async () => {
        await runPipeline([createMessage('$$client_ingestion_warning', 'localStorage full')])

        const warnings = warningsProduced()
        expect(warnings).toHaveLength(1)
        expect(warnings[0].team_id).toBe(team.id)
        expect(warnings[0].type).toBe('client_ingestion_warning')
        expect(parseJSON(warnings[0].details).message).toBe('localStorage full')
        expect(dlqProduced()).toHaveLength(0)
    })

    it.each(['$pageview', '$identify', 'custom_event'])(
        'DLQs %s events instead of emitting warnings',
        async (event) => {
            await runPipeline([createMessage(event)])

            expect(dlqProduced()).toHaveLength(1)
            expect(warningsProduced()).toHaveLength(0)
        }
    )
})
