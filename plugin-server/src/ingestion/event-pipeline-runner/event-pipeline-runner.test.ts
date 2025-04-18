import { DateTime } from 'luxon'

import { KAFKA_EVENTS_JSON, KAFKA_INGESTION_WARNINGS } from '~/src/config/kafka-topics'
import { UUIDT } from '~/src/utils/utils'
import { getProducedKafkaMessagesForTopic, mockProducer } from '~/tests/helpers/mocks/producer.mock'
import { forSnapshot } from '~/tests/helpers/snapshots'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { Hub, PipelineEvent, Team } from '../../../src/types'
import { closeHub, createHub } from '../../../src/utils/db/hub'
import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { EventPipelineRunnerV2 } from './event-pipeline-runner'

describe('EventPipelineRunner', () => {
    let hub: Hub
    let team: Team
    let fixedTime: DateTime
    let hogTransformer: HogTransformerService

    const createEvent = (event?: Partial<PipelineEvent>): PipelineEvent => ({
        distinct_id: 'user-1',
        uuid: new UUIDT().toString(),
        token: team.api_token,
        ip: '127.0.0.1',
        site_url: 'us.posthog.com',
        now: fixedTime.toISO()!,
        event: '$pageview',
        properties: {
            $current_url: 'http://localhost:8000',
        },
        ...event,
    })

    const createRunner = (event?: Partial<PipelineEvent>) => {
        const runner = new EventPipelineRunnerV2(hub, createEvent(event), hogTransformer)
        jest.spyOn(runner as any, 'captureIngestionWarning')
        jest.spyOn(runner as any, 'dropEvent')
        return runner
    }

    beforeEach(async () => {
        fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())

        await resetTestDatabase()
        hub = await createHub()
        hub.kafkaProducer = mockProducer
        team = await getFirstTeam(hub)
        hogTransformer = new HogTransformerService(hub)
        await hogTransformer.start()
    })

    afterEach(async () => {
        jest.restoreAllMocks()
        await hogTransformer.stop()
        await closeHub(hub)
    })

    afterAll(() => {
        jest.useRealTimers()
    })

    describe('team resolution', () => {
        it('should drop events without a found token', async () => {
            const runner = createRunner({
                token: 'not-found',
            })
            await runner.run()

            expect(jest.mocked(runner['dropEvent'])).toHaveBeenCalledWith('invalid_token')
            expect(getProducedKafkaMessagesForTopic(KAFKA_EVENTS_JSON)).toHaveLength(0)
        })

        it('should drop events without a found team_id', async () => {
            const runner = createRunner({
                team_id: 9999,
            })
            await runner.run()
            expect(jest.mocked(runner['dropEvent'])).toHaveBeenCalledWith('invalid_token')
            expect(getProducedKafkaMessagesForTopic(KAFKA_EVENTS_JSON)).toHaveLength(0)
        })

        it('should not drop events with a valid token', async () => {
            const runner = createRunner({
                token: team.api_token,
            })
            await runner.run()
            expect(jest.mocked(runner['captureIngestionWarning'])).toHaveBeenCalledTimes(0)
            expect(getProducedKafkaMessagesForTopic(KAFKA_EVENTS_JSON)).toHaveLength(1)
        })

        it('should not drop events with a valid team_id', async () => {
            const runner = createRunner({
                token: '',
                team_id: team.id,
            })
            await runner.run()
            expect(jest.mocked(runner['captureIngestionWarning'])).toHaveBeenCalledTimes(0)
            expect(getProducedKafkaMessagesForTopic(KAFKA_EVENTS_JSON)).toHaveLength(1)
        })
    })

    describe('error handling and ingestion warnings', () => {
        it('should rethrow unhandled errors', async () => {
            const runner = createRunner()
            jest.spyOn(runner as any, 'getTeam').mockRejectedValue(new Error('test'))
            await expect(runner.run()).rejects.toThrow()
            expect(jest.mocked(runner['captureIngestionWarning'])).toHaveBeenCalledTimes(0)
        })

        it('should capture ingestion warnings without throwing for $$client_ingestion_warning events', async () => {
            const runner = createRunner({
                event: '$$client_ingestion_warning',
                properties: {
                    $$client_ingestion_warning_message: 'the message',
                },
            })
            await runner.run()
            expect(jest.mocked(runner['captureIngestionWarning'])).toHaveBeenCalledTimes(1)
            expect(forSnapshot(getProducedKafkaMessagesForTopic(KAFKA_INGESTION_WARNINGS))).toMatchObject([
                {
                    topic: 'clickhouse_ingestion_warnings_test',
                    value: {
                        details: `{"eventUuid":"<REPLACED-UUID-0>","event":"$$client_ingestion_warning","distinctId":"user-1","message":"the message"}`,
                        team_id: 2,
                        type: 'client_ingestion_warning',
                    },
                },
            ])
        })

        it('should capture ingestion warning for bad uuid', async () => {
            const runner = createRunner({
                uuid: 'bad-uuid',
            })

            await expect(runner.run()).rejects.toThrow()
            expect(jest.mocked(runner['captureIngestionWarning'])).toHaveBeenCalledTimes(1)
            expect(forSnapshot(getProducedKafkaMessagesForTopic(KAFKA_INGESTION_WARNINGS))).toMatchObject([
                {
                    topic: 'clickhouse_ingestion_warnings_test',
                    value: {
                        details: '{"eventUuid":"bad-uuid","event":"$pageview","distinctId":"user-1"}',
                        team_id: 2,
                        type: 'invalid_event_uuid',
                    },
                },
            ])
        })

        it.each(['$identify', '$create_alias', '$merge_dangerously', '$groupidentify'])(
            'drops event %s that are not allowed when $process_person_profile=false',
            async (eventName) => {
                const runner = createRunner({
                    properties: { $process_person_profile: false },
                    event: eventName,
                })

                await expect(() => runner.run()).rejects.toThrow()
                expect(jest.mocked(runner['captureIngestionWarning'])).toHaveBeenCalledTimes(1)
                expect(forSnapshot(getProducedKafkaMessagesForTopic(KAFKA_INGESTION_WARNINGS))).toMatchObject([
                    {
                        key: null,
                        topic: 'clickhouse_ingestion_warnings_test',
                        value: {
                            details: `{"eventUuid":"<REPLACED-UUID-0>","event":"${eventName}","distinctId":"user-1"}`,
                            source: 'plugin-server',
                            team_id: 2,
                            timestamp: '2025-01-01 00:00:00.000',
                            type: 'invalid_event_when_process_person_profile_is_false',
                        },
                    },
                ])
            }
        )
    })

    describe('person processing', () => {})
})
