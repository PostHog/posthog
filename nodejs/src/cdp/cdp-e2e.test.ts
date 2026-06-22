import { MockKafkaProducerWrapper } from '~/tests/helpers/mocks/producer.mock'
import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { KafkaProducerObserver } from '~/tests/helpers/mocks/producer.spy'

import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { waitForExpect } from '~/tests/helpers/expectations'
import { TEST_KAFKA_TOPICS, ensureKafkaTopics } from '~/tests/helpers/kafka'
import { forSnapshot } from '~/tests/helpers/snapshots'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { CdpCyclotronWorker } from '../../src/cdp/consumers/cdp-cyclotron-worker.consumer'
import { HogFunctionInvocationGlobals, HogFunctionType } from '../../src/cdp/types'
import { KAFKA_APP_METRICS_2, KAFKA_LOG_ENTRIES } from '../../src/config/kafka-topics'
import { KafkaProducerWrapper } from '../../src/kafka/producer'
import { Hub, Team } from '../../src/types'
import { closeHub, createHub } from '../../src/utils/db/hub'
import { logger } from '../utils/logger'
import { HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from './_tests/examples'
import {
    insertHogFunction as _insertHogFunction,
    createHogExecutionGlobals,
    insertIntegration,
} from './_tests/fixtures'
import { CdpEventsConsumer } from './consumers/cdp-events.consumer'
import { CyclotronJobQueueKafka } from './services/job-queue/job-queue-kafka'
import { CyclotronJobQueuePostgresV2 } from './services/job-queue/job-queue-postgres-v2'
import { compileHog } from './templates/compiler'

const ActualKafkaProducerWrapper = jest.requireActual('../../src/kafka/producer').KafkaProducerWrapper

describe('CDP Consumer loop', () => {
    jest.setTimeout(20000)

    describe('e2e fetch call', () => {
        let eventsConsumer: CdpEventsConsumer
        let cyclotronWorker: CdpCyclotronWorker

        let hub: Hub
        let kafkaProducer: KafkaProducerWrapper = undefined as unknown as KafkaProducerWrapper
        let team: Team
        let fnFetchNoFilters: HogFunctionType
        let globals: HogFunctionInvocationGlobals
        let mockProducerObserver: KafkaProducerObserver

        const insertHogFunction = async (hogFunction: Partial<HogFunctionType>): Promise<HogFunctionType> => {
            const item = await _insertHogFunction(hub.postgres, team.id, hogFunction)
            return item
        }

        beforeEach(async () => {
            // Each `KafkaProducerWrapper.create()` call (e.g. inside each cyclotron job
            // queue) gets a fresh real producer it owns and disconnects on stop. The
            // CDP outputs registry uses the dedicated `kafkaProducer` below — a separate
            // real producer the test owns, observes, and disconnects in `afterEach`.
            MockKafkaProducerWrapper.create = jest.fn((...args) => {
                return ActualKafkaProducerWrapper.create(...args)
            })

            await ensureKafkaTopics(TEST_KAFKA_TOPICS)

            await resetTestDatabase()
            hub = await createHub()

            kafkaProducer = await ActualKafkaProducerWrapper.create(hub.KAFKA_CLIENT_RACK)
            mockProducerObserver = new KafkaProducerObserver(kafkaProducer)

            team = await getFirstTeam(hub.postgres)
            mockProducerObserver.resetKafkaProducer()

            hub.CDP_FETCH_RETRIES = 2
            hub.CDP_FETCH_BACKOFF_BASE_MS = 100 // fast backoff
            hub.CDP_CYCLOTRON_COMPRESS_KAFKA_DATA = true

            // Include integration parsing as part of the e2e check
            await insertIntegration(hub.postgres, team.id, {
                id: 1,
                kind: 'slack',
                config: {},
                sensitive_config: {
                    access_token: hub.encryptedFields.encrypt('super-secret-token'),
                },
            })

            const hog = `
            let res := fetch(inputs.url, {
                'headers': {
                  'Authorization': f'Bearer {inputs.oauth.access_token}',
                },
                'body': inputs.body,
                'method': inputs.method
            });

            print('Fetch response:', res);
            `

            fnFetchNoFilters = await insertHogFunction({
                type: 'destination',
                hog: hog,
                bytecode: await compileHog(hog),
                inputs_schema: [
                    ...(HOG_INPUTS_EXAMPLES.simple_fetch.inputs_schema ?? []),
                    { key: 'oauth', type: 'integration', label: 'Slack', secret: false, required: true },
                ],
                inputs: {
                    ...HOG_INPUTS_EXAMPLES.simple_fetch.inputs,
                    oauth: {
                        value: 1,
                    },
                },
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            const kafkaQueue = new CyclotronJobQueueKafka(hub.KAFKA_CLIENT_RACK, hub, hub.CONSUMER_BATCH_SIZE)
            const postgresV2Queue = new CyclotronJobQueuePostgresV2(hub.CONSUMER_BATCH_SIZE, hub)

            eventsConsumer = new CdpEventsConsumer(hub, createCdpConsumerDeps(hub, kafkaProducer), {
                hogQueue: kafkaQueue,
                hogflowQueue: postgresV2Queue,
            })
            await eventsConsumer.start()

            cyclotronWorker = new CdpCyclotronWorker(hub, createCdpConsumerDeps(hub, kafkaProducer), kafkaQueue)
            await cyclotronWorker.start()

            globals = createHogExecutionGlobals({
                project: {
                    id: team.id,
                } as any,
                event: {
                    uuid: 'b3a1fe86-b10c-43cc-acaf-d208977608d0',
                    event: '$pageview',
                    properties: {
                        $current_url: 'https://posthog.com',
                        $lib_version: '1.0.0',
                    },
                    timestamp: '2024-09-03T09:00:00Z',
                } as any,
            })

            mockFetch.mockResolvedValue({
                status: 200,
                json: () => Promise.resolve({ success: true }),
                text: () => Promise.resolve(JSON.stringify({ success: true })),
                headers: { 'Content-Type': 'application/json' },
                dump: () => Promise.resolve(),
            })

            expect(mockProducerObserver.getProducedKafkaMessages()).toHaveLength(0)
        })

        afterEach(async () => {
            await Promise.all([
                eventsConsumer?.stop().then(() => console.log('Stopped eventsConsumer')),
                cyclotronWorker?.stop().then(() => console.log('Stopped cyclotronWorker')),
            ])
            await kafkaProducer.disconnect()
            await closeHub(hub)
            mockProducerObserver.resetKafkaProducer()
        })

        afterAll(() => {
            jest.useRealTimers()
        })

        /**
         * Tests here are somewhat expensive so should mostly simulate happy paths and the more e2e scenarios
         */

        it('should invoke a function in the worker loop until completed', async () => {
            const { invocations } = await eventsConsumer.processBatch([globals])
            expect(invocations).toHaveLength(1)

            try {
                await waitForExpect(() => {
                    expect(mockProducerObserver.getProducedKafkaMessagesForTopic('log_entries_test')).toHaveLength(2)
                }, 5000)
            } catch (e) {
                logger.warn('[TESTS] Failed to wait for log messages', {
                    messages: mockProducerObserver.getProducedKafkaMessages(),
                })
                throw e
            }

            expect(mockFetch).toHaveBeenCalledTimes(1)

            expect(mockFetch.mock.calls[0]).toMatchInlineSnapshot(`
                [
                  "https://example.com/posthog-webhook",
                  {
                    "body": "{"event":{"uuid":"b3a1fe86-b10c-43cc-acaf-d208977608d0","event":"$pageview","elements_chain":"","distinct_id":"distinct_id","url":"http://localhost:8000/events/1","properties":{"$current_url":"https://posthog.com","$lib_version":"1.0.0"},"timestamp":"2024-09-03T09:00:00Z"},"groups":{},"nested":{"foo":"http://localhost:8000/events/1"},"person":{"id":"uuid","name":"test","url":"http://localhost:8000/persons/1","properties":{"email":"test@posthog.com","first_name":"Pumpkin"}},"event_url":"http://localhost:8000/events/1-test"}",
                    "headers": {
                      "Authorization": "Bearer super-secret-token",
                    },
                    "method": "POST",
                  },
                ]
            `)

            const logMessages = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_LOG_ENTRIES)
            const metricsMessages = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)

            expect(metricsMessages).toMatchObject([
                {
                    topic: 'clickhouse_app_metrics2_test',
                    value: {
                        app_source: 'hog_function',
                        app_source_id: fnFetchNoFilters.id.toString(),
                        count: 1,
                        metric_kind: 'other',
                        metric_name: 'triggered',
                        team_id: 2,
                    },
                },
                {
                    topic: 'clickhouse_app_metrics2_test',
                    value: {
                        app_source: 'hog_function',
                        app_source_id: '_event_trigger',
                        count: 1,
                        metric_kind: 'billing',
                        metric_name: 'billable_invocation',
                        team_id: 2,
                    },
                },
                {
                    topic: 'clickhouse_app_metrics2_test',
                    value: {
                        app_source: 'hog_function',
                        app_source_id: fnFetchNoFilters.id.toString(),
                        count: 1,
                        metric_kind: 'other',
                        metric_name: 'fetch',
                        team_id: 2,
                    },
                },
                {
                    topic: 'clickhouse_app_metrics2_test',
                    value: {
                        app_source: 'hog_function',
                        app_source_id: fnFetchNoFilters.id.toString(),
                        count: 1,
                        metric_kind: 'success',
                        metric_name: 'succeeded',
                        team_id: 2,
                    },
                },
            ])

            expect(logMessages).toMatchObject([
                {
                    topic: 'log_entries_test',
                    value: {
                        level: 'info',
                        log_source: 'hog_function',
                        log_source_id: fnFetchNoFilters.id.toString(),
                        message: `Fetch response:, {"status":200,"body":{"success":true}}`,
                        team_id: 2,
                    },
                },
                {
                    topic: 'log_entries_test',
                    value: {
                        level: 'debug',
                        log_source: 'hog_function',
                        log_source_id: fnFetchNoFilters.id.toString(),
                        message: expect.stringContaining('Function completed in'),
                        team_id: 2,
                    },
                },
            ])
        })

        // E2E coverage for the AWS SigV4 fetch-time signing path. The regression this
        // guards against: secrets land in `encrypted_inputs` after `move_secret_inputs`
        // runs on save, so the executor has to look them up there — not in `inputs`,
        // which is empty for `secret: true` keys. If we ever break that lookup the
        // upstream gets an unsigned request and AWS 401s. Also covers retry — the
        // second attempt must carry a freshly-signed Authorization header, not a
        // reused stale one from the first attempt.
        it('should sign aws sigv4 fetches from encrypted_inputs on both initial attempt and retry', async () => {
            const ACCESS_KEY = 'AKIDEXAMPLE'
            const SECRET_KEY = 'wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY'

            const sigv4FetchCalls: Array<{ url: string; opts: any }> = []
            let kinesisCallCount = 0
            mockFetch.mockImplementation((url: string, opts: any) => {
                if (url.includes('kinesis.')) {
                    sigv4FetchCalls.push({ url, opts })
                    kinesisCallCount++
                    if (kinesisCallCount === 1) {
                        // Delay the first 500 by long enough that attempt-2 signs in a
                        // different wall-clock second. X-Amz-Date is second-resolution,
                        // so without this delay both attempts would land in the same
                        // second and produce identical signatures — masking whether the
                        // retry actually re-signed or just reused the original payload.
                        return new Promise((resolve) =>
                            setTimeout(
                                () =>
                                    resolve({
                                        status: 500,
                                        json: () => Promise.resolve({}),
                                        text: () => Promise.resolve(''),
                                        headers: {},
                                        dump: () => Promise.resolve(),
                                    }),
                                1500
                            )
                        )
                    }
                }
                return Promise.resolve({
                    status: 200,
                    json: () => Promise.resolve({ ok: true }),
                    text: () => Promise.resolve('{"ok":true}'),
                    headers: { 'Content-Type': 'application/json' },
                    dump: () => Promise.resolve(),
                })
            })

            const hog = `
            let res := fetch('https://kinesis.us-east-1.amazonaws.com', {
                'method': 'POST',
                'headers': {
                    'Content-Type': 'application/x-amz-json-1.1',
                    'X-Amz-Target': 'Kinesis_20131202.PutRecord',
                },
                'body': '{"StreamName":"s","PartitionKey":"p","Data":"ZA=="}',
                'aws_sigv4': {
                    'service': 'kinesis',
                    'region': 'us-east-1',
                    'access_key_id_input': 'aws_access_key_id',
                    'secret_access_key_input': 'aws_secret_access_key',
                },
            });
            print('Fetch response:', res);
            `

            await insertHogFunction({
                type: 'destination',
                hog,
                bytecode: await compileHog(hog),
                inputs_schema: [
                    { key: 'aws_access_key_id', type: 'string', label: 'AKID', secret: true, required: true },
                    { key: 'aws_secret_access_key', type: 'string', label: 'SK', secret: true, required: true },
                ],
                inputs: {},
                // Mirror what Django's `move_secret_inputs` produces in prod: secret
                // inputs are Fernet-encrypted on `encrypted_inputs`. The Node manager
                // detects the string form and decrypts back to the plaintext map shape
                // before the executor sees the function.
                encrypted_inputs: hub.encryptedFields.encrypt(
                    JSON.stringify({
                        aws_access_key_id: { value: ACCESS_KEY },
                        aws_secret_access_key: { value: SECRET_KEY },
                    })
                ),
                ...HOG_FILTERS_EXAMPLES.no_filters,
            } as any)

            // The default `fnFetchNoFilters` from beforeEach also matches this event;
            // we expect both to fire, but we only inspect the Kinesis ones.
            await eventsConsumer.processBatch([globals])

            await waitForExpect(() => {
                expect(sigv4FetchCalls.length).toBeGreaterThanOrEqual(2)
            }, 5000).catch((e) => {
                logger.warn('[TESTS] Expected two Kinesis fetch attempts (initial + retry)', {
                    sigv4FetchCount: sigv4FetchCalls.length,
                    allFetchCalls: mockFetch.mock.calls.length,
                })
                throw e
            })

            // Every attempt (including the retry) must carry a fresh SigV4 Authorization
            // header derived from the decrypted `encrypted_inputs` map. A regression in
            // the lookup path would either crash with the "input not found" error or
            // ship an unsigned request — both visible here.
            const sigv4Authorizations = sigv4FetchCalls.slice(0, 2).map(({ opts }) => {
                const headers = (opts?.headers ?? {}) as Record<string, string>
                return headers['Authorization'] ?? headers.authorization
            })
            const sigv4AmzDates = sigv4FetchCalls.slice(0, 2).map(({ opts }) => {
                const headers = (opts?.headers ?? {}) as Record<string, string>
                return headers['X-Amz-Date'] ?? headers['x-amz-date']
            })

            for (const auth of sigv4Authorizations) {
                expect(auth).toMatch(
                    /^AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE\/\d{8}\/us-east-1\/kinesis\/aws4_request, SignedHeaders=[a-z0-9;-]+, Signature=[a-f0-9]{64}$/
                )
            }

            // The actual bug this whole PR exists to fix: a retry must NOT reuse the
            // signature from the first attempt. The 1.5s delay on the 500 response
            // forces the two attempts to sign in different wall-clock seconds, so a
            // correct implementation produces different X-Amz-Date values and therefore
            // different signatures. If we ever regress to "sign once, reuse on retry"
            // these two would match and AWS would return InvalidSignatureException in
            // production whenever the retry crossed the 5-minute signature window.
            expect(sigv4AmzDates[0]).not.toEqual(sigv4AmzDates[1])
            expect(sigv4Authorizations[0]).not.toEqual(sigv4Authorizations[1])
        })

        it('should handle fetch failures with retries', async () => {
            mockFetch.mockImplementation(() => {
                return Promise.resolve({
                    status: 500,
                    headers: {},
                    json: () => Promise.resolve({ error: 'Server error' }),
                    text: () => Promise.resolve(JSON.stringify({ error: 'Server error' })),
                    dump: () => Promise.resolve(),
                })
            })

            const { invocations } = await eventsConsumer.processBatch([globals])

            expect(invocations).toHaveLength(1)

            await waitForExpect(() => {
                expect(mockProducerObserver.getProducedKafkaMessages().length).toBeGreaterThan(3)
            }, 5000).catch((e) => {
                logger.warn('[TESTS] Failed to wait for log messages', {
                    messages: mockProducerObserver.getProducedKafkaMessages(),
                })
                throw e
            })

            const logMessages = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_LOG_ENTRIES)

            // Ignore the last message as it is non-deterministic
            expect(
                forSnapshot(
                    logMessages
                        .map((m) => m.value.message)
                        // Sorted compare as the messages can get logged in different orders
                        .sort()
                )
            ).toEqual([
                'Fetch response:, {"status":500,"body":{"error":"Server error"}}',
                expect.stringContaining('Function completed in '),
                expect.stringContaining('HTTP fetch failed on attempt 1 with status code 500. Retrying in '),
                expect.stringContaining('HTTP fetch failed on attempt 2 with status code 500. Retrying in '),
            ])
        })
    })
})
