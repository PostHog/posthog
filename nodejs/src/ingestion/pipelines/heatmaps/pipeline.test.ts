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
import { CookielessManager } from '~/ingestion/common/cookieless/cookieless-manager'
import { EventFilterManager } from '~/ingestion/common/event-filters'
import { createOkContext } from '~/ingestion/framework/helpers'
import { drop, ok } from '~/ingestion/framework/results'
import { createTestTeam } from '~/tests/helpers/team'

import { HEATMAPS_OUTPUT } from './outputs'
import { HeatmapsPipelineConfig, createHeatmapsPipeline } from './pipeline'

jest.mock('~/common/utils/logger', () => ({
    logger: { debug: jest.fn(), info: jest.fn(), warn: jest.fn(), error: jest.fn() },
}))

const HEATMAPS_TOPIC = 'clickhouse_heatmap_events_test'
const DLQ_TOPIC = 'events_plugin_ingestion_dlq_test'

describe('HeatmapsPipeline', () => {
    let mockKafkaProducer: jest.Mocked<KafkaProducerWrapper>
    let mockTeamManager: jest.Mocked<TeamManager>
    let mockEventIngestionRestrictionManager: jest.Mocked<EventIngestionRestrictionManager>
    let mockEventFilterManager: jest.Mocked<EventFilterManager>
    let mockCookielessManager: jest.Mocked<CookielessManager>
    let promiseScheduler: PromiseScheduler
    let config: HeatmapsPipelineConfig

    const team = createTestTeam({ id: 123, api_token: 'token-123', heatmaps_opt_in: true })

    const heatmapProperties = {
        $session_id: 'session-1',
        $viewport_width: 1024,
        $viewport_height: 768,
        $current_url: 'http://localhost:3000/',
        $heatmap_data: {
            'http://localhost:3000/': [{ x: 100, y: 200, target_fixed: false, type: 'click' }],
        },
    }

    const createMessage = (event: string, properties: Record<string, any> = heatmapProperties): Message => {
        const distinctId = 'user-1'
        const eventData = {
            event,
            distinct_id: distinctId,
            uuid: new UUIDT().toString(),
            timestamp: '2024-01-01T00:00:00Z',
            properties,
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
            topic: 'heatmaps_ingestion',
            partition: 0,
            offset: 0,
            size: 0,
            key: Buffer.from(distinctId),
        } as Message
    }

    const runPipeline = async (messages: Message[]): Promise<void> => {
        const pipeline = createHeatmapsPipeline(config)
        const batch = messages.map((message) => createOkContext({ message }, { message }))
        await pipeline.feed(batch)
        let result = await pipeline.next()
        while (result !== null) {
            for (const sideEffect of result.sideEffects ?? []) {
                void promiseScheduler.schedule(sideEffect)
            }
            result = await pipeline.next()
        }
        await promiseScheduler.waitForAll()
    }

    const heatmapsProducedFor = (): any[] =>
        mockKafkaProducer.queueMessages.mock.calls
            .map((call) => call[0])
            .filter((arg: any) => arg.topic === HEATMAPS_TOPIC)
            .flatMap((arg: any) => arg.messages.map((m: { value: Buffer }) => parseJSON(m.value.toString())))

    const dlqProducedFor = (): any[] =>
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

        // Passthrough by default: events round-trip unchanged. The apply step reads `.value.event`
        // from each result, so returning `ok(e)` leaves the distinct id untouched.
        mockCookielessManager = {
            doBatch: jest.fn().mockImplementation((events: any[]) => Promise.resolve(events.map((e) => ok(e)))),
        } as unknown as jest.Mocked<CookielessManager>

        promiseScheduler = new PromiseScheduler()

        config = {
            outputs: new IngestionOutputs({
                [HEATMAPS_OUTPUT]: new SingleIngestionOutput(
                    HEATMAPS_OUTPUT,
                    HEATMAPS_TOPIC,
                    mockKafkaProducer,
                    'test'
                ),
                [DLQ_OUTPUT]: new SingleIngestionOutput(DLQ_OUTPUT, DLQ_TOPIC, mockKafkaProducer, 'test'),
                [INGESTION_WARNINGS_OUTPUT]: new SingleIngestionOutput(
                    INGESTION_WARNINGS_OUTPUT,
                    'clickhouse_ingestion_warnings_test',
                    mockKafkaProducer,
                    'test'
                ),
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
            cookielessManager: mockCookielessManager,
            promiseScheduler,
        }
    })

    it('extracts heatmap data from $$heatmap events', async () => {
        await runPipeline([createMessage('$$heatmap')])

        const heatmaps = heatmapsProducedFor()
        expect(heatmaps).toHaveLength(1)
        expect(heatmaps[0].type).toBe('click')
        expect(heatmaps[0].session_id).toBe('session-1')
        expect(dlqProducedFor()).toHaveLength(0)
    })

    it('extracts heatmaps using the cookieless-rewritten distinct id', async () => {
        // Cookieless events arrive with a sentinel distinct id; the cookieless step rewrites it to a
        // deterministic hash, which extraction must use.
        mockCookielessManager.doBatch.mockImplementation((events: any[]) =>
            Promise.resolve(events.map((e) => ok({ ...e, event: { ...e.event, distinct_id: 'hashed-cookieless-id' } })))
        )

        await runPipeline([createMessage('$$heatmap')])

        const heatmaps = heatmapsProducedFor()
        expect(heatmaps).toHaveLength(1)
        expect(heatmaps[0].distinct_id).toBe('hashed-cookieless-id')
        expect(mockCookielessManager.doBatch).toHaveBeenCalledTimes(1)
    })

    it('drops $$heatmap events that cookieless processing rejects', async () => {
        mockCookielessManager.doBatch.mockImplementation((events: any[]) =>
            Promise.resolve(events.map(() => drop('cookieless_team_disabled')))
        )

        await runPipeline([createMessage('$$heatmap')])

        expect(heatmapsProducedFor()).toHaveLength(0)
        expect(dlqProducedFor()).toHaveLength(0)
    })

    it.each(['$pageview', '$autocapture', '$identify', '$exception', '$$client_ingestion_warning', 'custom_event'])(
        'DLQs %s events instead of processing them as heatmaps',
        async (eventName) => {
            await runPipeline([createMessage(eventName)])

            expect(dlqProducedFor()).toHaveLength(1)
            expect(heatmapsProducedFor()).toHaveLength(0)
        }
    )

    it('drops $$heatmap events when the team has opted out', async () => {
        const optedOutTeam = createTestTeam({ id: 456, api_token: 'token-456', heatmaps_opt_in: false })
        mockTeamManager.getTeamByToken.mockResolvedValue(optedOutTeam)

        await runPipeline([createMessage('$$heatmap')])

        // Opt-out is a drop, not a DLQ — nothing is produced anywhere.
        expect(heatmapsProducedFor()).toHaveLength(0)
        expect(dlqProducedFor()).toHaveLength(0)
    })
})
