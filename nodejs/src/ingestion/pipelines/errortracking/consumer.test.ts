import { mockProducer, mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'

import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { HogTransformer } from '~/common/hog-transformations/hog-transformer.interface'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { SingleIngestionOutput } from '~/common/outputs/single-ingestion-output'
import { parseJSON } from '~/common/utils/json-parse'
import { UUIDT } from '~/common/utils/utils'
import { Component, newScope } from '~/ingestion/common/scopes'
import { IngestionTestInfra, createIngestionTestInfra } from '~/tests/helpers/ingestion-e2e'
import { createTestTeamFixture } from '~/tests/helpers/sql'
import { PipelineEvent, Team } from '~/types'

import { ErrorTrackingLaneConfig, createErrorTrackingConsumer } from './consumer'
import { ErrorTrackingOutputs } from './error-tracking-pipeline'

jest.setTimeout(60000)

type BatchHandler = (messages: Message[]) => Promise<{ backgroundTask?: Promise<unknown> }>

// The common consumer connects its own Kafka consumer; capture the batch handler it
// registers so tests can drive batches without a broker.
let mockBatchHandler: BatchHandler | undefined
jest.mock('~/common/kafka/consumer', () => ({
    ...jest.requireActual('~/common/kafka/consumer'),
    createKafkaConsumer: jest.fn(() => ({
        connect: jest.fn((handler: BatchHandler) => {
            mockBatchHandler = handler
            return Promise.resolve()
        }),
        disconnect: jest.fn().mockResolvedValue(undefined),
        isHealthy: jest.fn().mockReturnValue({ status: 'ok' }),
    })),
}))

// The lane owns its personhog client and reads persons/groups through it; there is no
// personhog server in tests, so stand in for the client and the read repositories.
jest.mock('~/common/personhog/personhog-client-component', () => ({
    PersonHogClientComponent: jest.fn().mockImplementation(() => ({
        start: () => Promise.resolve({ value: {}, stop: () => Promise.resolve() }),
    })),
}))
jest.mock('~/common/personhog/personhog-person-read-repository', () => ({
    PersonHogPersonReadRepository: jest.fn().mockImplementation(() => ({
        fetchPerson: jest.fn().mockResolvedValue(undefined),
        fetchPersonsByDistinctIds: jest.fn().mockResolvedValue([]),
        fetchPersonsByPersonIds: jest.fn().mockResolvedValue([]),
        fetchDistinctIdsForPersons: jest.fn().mockResolvedValue({}),
    })),
}))
jest.mock('~/common/personhog/personhog-group-read-repository', () => ({
    PersonHogGroupReadRepository: jest.fn().mockImplementation(() => ({
        fetchGroupsByKeys: jest.fn().mockResolvedValue([]),
        fetchGroupTypesByTeamIds: jest.fn().mockResolvedValue({}),
        fetchGroupTypesByProjectIds: jest.fn().mockResolvedValue({}),
    })),
}))

jest.mock('~/common/utils/posthog', () => {
    const original = jest.requireActual('~/common/utils/posthog')
    return {
        ...original,
        captureException: jest.fn(),
    }
})

jest.mock('~/common/utils/token-bucket', () => {
    const mockConsume = jest.fn().mockReturnValue(true)
    return {
        ...jest.requireActual('~/common/utils/token-bucket'),
        IngestionWarningLimiter: {
            consume: mockConsume,
        },
    }
})

jest.mock('~/common/utils/logger', () => ({
    logger: {
        debug: jest.fn(),
        info: jest.fn(),
        warn: jest.fn(),
        error: jest.fn(),
    },
}))

jest.mock('./cymbal', () => ({
    CymbalClient: jest.fn().mockImplementation(() => ({
        processExceptions: jest.fn().mockImplementation((items) =>
            items.map((item: any) => ({
                uuid: item.request.uuid,
                event: item.request.event,
                team_id: item.request.team_id,
                timestamp: item.request.timestamp,
                properties: {
                    ...item.request.properties,
                    $exception_fingerprint: `fingerprint-${item.request.uuid}`,
                    $exception_issue_id: `issue-${item.request.uuid}`,
                },
            }))
        ),
    })),
}))

const createMockHogTransformer = (): jest.Mocked<HogTransformer> => ({
    start: jest.fn().mockResolvedValue(undefined),
    stop: jest.fn().mockResolvedValue(undefined),
    transformEventAndProduceMessages: jest
        .fn()
        .mockImplementation((event) => Promise.resolve({ event, invocationResults: [] })),
    processInvocationResults: jest.fn().mockResolvedValue(undefined),
    prefetchHogFunctionsForTeams: jest.fn().mockResolvedValue(undefined),
})

const staticComponent = <T>(value: T): Component<T> => ({
    start: () => Promise.resolve({ value, stop: () => Promise.resolve() }),
})

let offsetIncrementer = 0

const createKafkaMessage = (event: PipelineEvent, token: string): Message => {
    const captureEvent = {
        uuid: event.uuid,
        distinct_id: event.distinct_id,
        ip: event.ip,
        now: event.now,
        token,
        data: JSON.stringify(event),
    }
    return {
        key: `${token}:${event.distinct_id}`,
        value: Buffer.from(JSON.stringify(captureEvent)),
        size: 1,
        topic: 'error_tracking_events_test',
        offset: offsetIncrementer++,
        timestamp: DateTime.now().toMillis(),
        partition: 1,
        headers: [
            { distinct_id: Buffer.from(event.distinct_id || '') },
            { token: Buffer.from(token) },
            { event: Buffer.from(event.event || '') },
            { uuid: Buffer.from(event.uuid || '') },
            { now: Buffer.from(event.now || '') },
        ],
    }
}

describe('createErrorTrackingConsumer', () => {
    let infra: IngestionTestInfra
    let team: Team
    let fixedTime: DateTime
    let mockHogTransformer: jest.Mocked<HogTransformer>
    let stopConsumer: () => Promise<void>

    const startConsumer = async (infra: IngestionTestInfra): Promise<void> => {
        const config: ErrorTrackingLaneConfig = {
            ...infra.config,
            INGESTION_CONSUMER_GROUP_ID: infra.config.ERROR_TRACKING_CONSUMER_GROUP_ID,
            INGESTION_CONSUMER_CONSUME_TOPIC: infra.config.ERROR_TRACKING_CONSUMER_CONSUME_TOPIC,
        }
        const outputs: ErrorTrackingOutputs = new IngestionOutputs({
            events: new SingleIngestionOutput(
                'events',
                infra.config.ERROR_TRACKING_CONSUMER_OUTPUT_TOPIC,
                mockProducer,
                'test'
            ),
            ingestion_warnings: new SingleIngestionOutput(
                'ingestion_warnings',
                'clickhouse_ingestion_warnings_test',
                mockProducer,
                'test'
            ),
            dlq: new SingleIngestionOutput('dlq', infra.config.ERROR_TRACKING_CONSUMER_DLQ_TOPIC, mockProducer, 'test'),
            overflow: new SingleIngestionOutput(
                'overflow',
                infra.config.ERROR_TRACKING_CONSUMER_OVERFLOW_TOPIC,
                mockProducer,
                'test'
            ),
            tophog: new SingleIngestionOutput('tophog', 'clickhouse_tophog_test', mockProducer, 'test'),
            app_metrics: new SingleIngestionOutput('app_metrics', 'clickhouse_app_metrics2_test', mockProducer, 'test'),
        })
        mockHogTransformer = createMockHogTransformer()

        const sharedScope = newScope('shared-test', (builder) =>
            builder
                .add('redisPool', staticComponent(infra.redisPool))
                .add('teamManager', staticComponent(infra.teamManager))
                .add('cookielessManager', staticComponent(infra.cookielessManager))
                .add('hogTransformer', staticComponent<HogTransformer>(mockHogTransformer))
                .add('outputs', staticComponent(outputs))
        )

        const started = await createErrorTrackingConsumer(config, sharedScope).start()
        stopConsumer = started.stop
    }

    const createEvent = (event?: Partial<PipelineEvent>): PipelineEvent => ({
        distinct_id: 'user-1',
        uuid: new UUIDT().toString(),
        ip: '127.0.0.1',
        site_url: 'us.posthog.com',
        now: fixedTime.toISO()!,
        event: '$exception',
        ...event,
        properties: {
            $exception_list: [
                {
                    type: 'Error',
                    value: 'Test error message',
                    mechanism: { type: 'generic', handled: true },
                },
            ],
            ...(event?.properties || {}),
        },
    })

    // A batch is fully processed once the returned background task (the
    // scheduled side-effect flush) has settled, matching the consumer loop.
    const handleBatch = async (messages: Message[]): Promise<void> => {
        const result = await mockBatchHandler!(messages)
        expect(result.backgroundTask).toBeDefined()
        await result.backgroundTask
    }

    beforeEach(async () => {
        fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())
        jest.spyOn(Date.prototype, 'toISOString').mockReturnValue(fixedTime.toISO()!)

        offsetIncrementer = 0
        mockBatchHandler = undefined
        infra = await createIngestionTestInfra()
        team = (await createTestTeamFixture(infra.postgres)).team

        await startConsumer(infra)
    })

    afterEach(async () => {
        await stopConsumer()
        await infra.close()
        mockProducerObserver.resetKafkaProducer()
    })

    afterAll(() => {
        jest.useRealTimers()
    })

    it('emits an exception event with Cymbal fields and drains the hog transformer once per batch', async () => {
        await handleBatch([createKafkaMessage(createEvent(), team.api_token)])

        const producedMessages = mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
        expect(producedMessages).toHaveLength(1)

        const event = producedMessages[0].value
        expect(event.event).toBe('$exception')
        expect(event.team_id).toBe(team.id)
        expect(event.distinct_id).toBe('user-1')
        // Error tracking always uses full person_mode to preserve group properties
        expect(event.person_mode).toBe('full')

        const properties = parseJSON(event.properties as string)
        expect(properties.$exception_fingerprint).toBeDefined()
        expect(properties.$exception_issue_id).toBeDefined()

        expect(mockHogTransformer.transformEventAndProduceMessages).toHaveBeenCalledTimes(1)
        expect(mockHogTransformer.processInvocationResults).toHaveBeenCalledTimes(1)
    })

    it('drops events whose token resolves to no team', async () => {
        await handleBatch([createKafkaMessage(createEvent(), 'invalid-token-that-does-not-exist')])

        expect(mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')).toHaveLength(0)
        expect(
            mockProducerObserver.getProducedKafkaMessagesForTopic(infra.config.ERROR_TRACKING_CONSUMER_DLQ_TOPIC)
        ).toHaveLength(0)
    })
})
