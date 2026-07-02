import { Message } from 'node-rdkafka'

import { ReadOnlyGroupTypeManager } from '~/common/groups/readonly-group-type-manager'
import { HogTransformer } from '~/common/hog-transformations/hog-transformer.interface'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { APP_METRICS_OUTPUT, DLQ_OUTPUT, INGESTION_WARNINGS_OUTPUT, OVERFLOW_OUTPUT } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { SingleIngestionOutput } from '~/common/outputs/single-ingestion-output'
import { PersonReadRepository } from '~/common/persons/repositories/person-repository'
import { EventIngestionRestrictionManager } from '~/common/utils/event-ingestion-restrictions'
import { EventSchemaEnforcementManager } from '~/common/utils/event-schema-enforcement-manager'
import { parseJSON } from '~/common/utils/json-parse'
import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { TeamManager } from '~/common/utils/team-manager'
import { UUIDT } from '~/common/utils/utils'
import { CookielessManager } from '~/ingestion/common/cookieless/cookieless-manager'
import { DisabledOverflowRedirect } from '~/ingestion/common/overflow-redirect/disabled-overflow-redirect'
import { TopHogWrapper } from '~/ingestion/framework/extensions/tophog'
import { createOkContext } from '~/ingestion/framework/helpers'
import { ok } from '~/ingestion/framework/results'
import { createTestTeam } from '~/tests/helpers/team'

import { AI_EVENTS_OUTPUT, EVENTS_OUTPUT } from './outputs'
import { AiIngestionPipelineConfig, createAiIngestionPipeline } from './pipeline'

jest.mock('~/common/utils/logger', () => ({
    logger: { debug: jest.fn(), info: jest.fn(), warn: jest.fn(), error: jest.fn() },
}))

const EVENTS_TOPIC = 'clickhouse_events_json_test'
const AI_EVENTS_TOPIC = 'clickhouse_ai_events_json_test'
const DLQ_TOPIC = 'events_plugin_ingestion_dlq_test'

describe('AiIngestionPipeline', () => {
    let mockKafkaProducer: jest.Mocked<KafkaProducerWrapper>
    let mockTeamManager: jest.Mocked<TeamManager>
    let mockEventIngestionRestrictionManager: jest.Mocked<EventIngestionRestrictionManager>
    let mockEventFilterManager: { getFilter: jest.Mock }
    let mockCookielessManager: jest.Mocked<CookielessManager>
    let mockHogTransformer: jest.Mocked<
        Pick<
            HogTransformer,
            'transformEventAndProduceMessages' | 'processInvocationResults' | 'prefetchTransformationStatesForTeams'
        >
    >
    let mockPersonRepository: jest.Mocked<PersonReadRepository>
    let mockGroupTypeManager: jest.Mocked<ReadOnlyGroupTypeManager>
    let promiseScheduler: PromiseScheduler
    let config: AiIngestionPipelineConfig

    const team = createTestTeam({ id: 123, api_token: 'token-123' })

    const createMessage = (event: string, properties: Record<string, any> = {}): Message => {
        const distinctId = 'user-1'
        const eventData = {
            event,
            distinct_id: distinctId,
            uuid: new UUIDT().toString(),
            timestamp: '2024-01-01T00:00:00Z',
            properties: { $ai_trace_id: 'trace-1', ...properties },
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
            topic: 'ai_ingestion',
            partition: 0,
            offset: 0,
            size: 0,
            key: Buffer.from(distinctId),
        } as Message
    }

    const runPipeline = async (messages: Message[]): Promise<void> => {
        const pipeline = createAiIngestionPipeline(config)
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

    const producedForTopic = (topic: string): any[] =>
        mockKafkaProducer.produce.mock.calls
            .map((call) => call[0])
            .filter((arg: any) => arg.topic === topic)
            .map((arg: any) => parseJSON(arg.value!.toString()))

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

        mockEventFilterManager = { getFilter: jest.fn().mockReturnValue(undefined) }

        mockCookielessManager = {
            doBatch: jest.fn().mockImplementation((events: any[]) => Promise.resolve(events.map((e) => ok(e)))),
        } as unknown as jest.Mocked<CookielessManager>

        mockHogTransformer = {
            transformEventAndProduceMessages: jest
                .fn()
                .mockImplementation((event) => Promise.resolve({ event, invocationResults: [] })),
            processInvocationResults: jest.fn().mockResolvedValue(undefined),
            prefetchTransformationStatesForTeams: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<
            Pick<
                HogTransformer,
                'transformEventAndProduceMessages' | 'processInvocationResults' | 'prefetchTransformationStatesForTeams'
            >
        >

        mockPersonRepository = {
            fetchPerson: jest.fn(),
            fetchPersonsByDistinctIds: jest.fn().mockResolvedValue([]),
            fetchPersonsByPersonIds: jest.fn(),
            fetchDistinctIdsForPersons: jest.fn().mockResolvedValue({}),
        } as unknown as jest.Mocked<PersonReadRepository>

        mockGroupTypeManager = {
            fetchGroupTypes: jest.fn().mockResolvedValue({}),
            fetchGroupTypesForProjects: jest.fn().mockResolvedValue({}),
        } as unknown as jest.Mocked<ReadOnlyGroupTypeManager>

        promiseScheduler = new PromiseScheduler()

        const single = (output: string, topic: string) =>
            new SingleIngestionOutput(output, topic, mockKafkaProducer, 'test')

        config = {
            outputs: new IngestionOutputs({
                [EVENTS_OUTPUT]: single(EVENTS_OUTPUT, EVENTS_TOPIC),
                [AI_EVENTS_OUTPUT]: single(AI_EVENTS_OUTPUT, AI_EVENTS_TOPIC),
                [DLQ_OUTPUT]: single(DLQ_OUTPUT, DLQ_TOPIC),
                [INGESTION_WARNINGS_OUTPUT]: single(INGESTION_WARNINGS_OUTPUT, 'clickhouse_ingestion_warnings_test'),
                [OVERFLOW_OUTPUT]: single(OVERFLOW_OUTPUT, 'events_plugin_ingestion_overflow_test'),
                [APP_METRICS_OUTPUT]: single(APP_METRICS_OUTPUT, 'clickhouse_app_metrics2_test'),
            }),
            teamManager: mockTeamManager,
            eventIngestionRestrictionManager: mockEventIngestionRestrictionManager,
            eventFilterManager: mockEventFilterManager as any,
            cookielessManager: mockCookielessManager,
            promiseScheduler,
            hogTransformer: mockHogTransformer as unknown as HogTransformer,
            personRepository: mockPersonRepository,
            groupTypeManager: mockGroupTypeManager,
            overflowEnabled: false,
            preservePartitionLocality: false,
            overflowRedirectService: new DisabledOverflowRedirect(),
            overflowLaneTTLRefreshService: new DisabledOverflowRedirect(),
            concurrentBatches: 1,
            cdpHogWatcherSampleRate: 1,
            eventSchemaEnforcementEnabled: false,
            eventSchemaEnforcementManager: {} as unknown as EventSchemaEnforcementManager,
            // No-op metrics wrapper — these tests assert pipeline output, not topHog counters.
            topHog: ((step) => step) as TopHogWrapper,
        }
    })

    it('double-writes AI events to both the events and ai_events outputs', async () => {
        await runPipeline([createMessage('$ai_generation')])

        expect(producedForTopic(EVENTS_TOPIC)).toHaveLength(1)
        expect(producedForTopic(AI_EVENTS_TOPIC)).toHaveLength(1)
        expect(producedForTopic(DLQ_TOPIC)).toHaveLength(0)
    })

    it.each(['$pageview', '$autocapture', '$identify', '$exception', 'custom_event'])(
        'DLQs non-AI %s events instead of processing them',
        async (eventName) => {
            await runPipeline([createMessage(eventName)])

            expect(producedForTopic(DLQ_TOPIC)).toHaveLength(1)
            expect(producedForTopic(EVENTS_TOPIC)).toHaveLength(0)
            expect(producedForTopic(AI_EVENTS_TOPIC)).toHaveLength(0)
        }
    )

    it('fetches person data read-only and never writes persons or groups', async () => {
        await runPipeline([createMessage('$ai_generation')])

        expect(mockPersonRepository.fetchPersonsByDistinctIds).toHaveBeenCalledTimes(1)
        expect(mockPersonRepository.fetchPersonsByDistinctIds).toHaveBeenCalledWith(
            [{ teamId: 123, distinctId: 'user-1' }],
            'fetch-person-batch-step'
        )
    })

    it('drains hog transformer invocation results once per batch', async () => {
        await runPipeline([createMessage('$ai_generation'), createMessage('$ai_span')])

        expect(mockHogTransformer.processInvocationResults).toHaveBeenCalledTimes(1)
    })

    it('prefetches hog transformation states for the batch teams before transforming', async () => {
        await runPipeline([createMessage('$ai_generation'), createMessage('$ai_span')])

        // Without this prefetch the transformer can't see Hog watcher's disabled state,
        // so disabled transformations would still run.
        expect(mockHogTransformer.prefetchTransformationStatesForTeams).toHaveBeenCalledWith([123])
    })
})
