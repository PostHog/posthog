import { RedisPool } from '../../types'
import { PostgresRouter } from '../../utils/db/postgres'
import { TeamManager, TeamManagerLifecycle } from '../../utils/team-manager'
import { CommonIngestionConsumer, CommonIngestionConsumerConfig } from '../common/common-ingestion-consumer'
import { AppMetricsOutput, DlqOutput, IngestionWarningsOutput } from '../common/outputs'
import { Lifecycle, newLifecycleBuilder } from '../common/service-registry'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { createClientWarningsConsumer } from './consumer'
import * as pipelineModule from './pipeline'

jest.mock('./pipeline')

describe('createClientWarningsConsumer', () => {
    function makeConfig(): CommonIngestionConsumerConfig {
        return {
            INGESTION_CONSUMER_GROUP_ID: 'g',
            INGESTION_CONSUMER_CONSUME_TOPIC: 't',
            INGESTION_PIPELINE: 'analytics',
            INGESTION_LANE: 'main',
            KAFKA_BATCH_START_LOGGING_ENABLED: false,
        }
    }

    function makeDeps() {
        const outputs = {
            checkTopics: jest.fn().mockResolvedValue([]),
        } as unknown as IngestionOutputs<IngestionWarningsOutput | DlqOutput | AppMetricsOutput>
        // The consumer factory chains off this lifecycle but doesn't start
        // it (start happens inside `consumer.start()`), so the shape only
        // has to be type-correct — no real postgres/redis/teamManager
        // needed for the tests in this file.
        const sharedLifecycle: Lifecycle<{
            postgres: PostgresRouter
            redisPool: RedisPool
            teamManager: TeamManager
        }> = newLifecycleBuilder()
            .register('postgres', {
                start: () => Promise.resolve({ service: {} as PostgresRouter, stop: () => Promise.resolve() }),
            })
            .register('redisPool', {
                start: () => Promise.resolve({ service: {} as RedisPool, stop: () => Promise.resolve() }),
            })
            .register('teamManager', new TeamManagerLifecycle({} as PostgresRouter))
            .build('shared-test')
        return {
            outputs,
            sharedLifecycle,
            staticDropEventTokens: [],
        }
    }

    beforeEach(() => {
        ;(pipelineModule.createClientWarningsPipeline as jest.Mock) = jest.fn().mockReturnValue({
            feed: jest.fn(),
            next: jest.fn(),
        })
    })

    it('returns a CommonIngestionConsumer', () => {
        const consumer = createClientWarningsConsumer(makeConfig(), makeDeps())
        expect(consumer).toBeInstanceOf(CommonIngestionConsumer)
    })

    it('defers pipeline construction until start time', () => {
        createClientWarningsConsumer(makeConfig(), makeDeps())

        // The pipeline factory runs inside `consumer.start()`, after the
        // lifecycle's services come up — not at consumer construction time.
        expect(pipelineModule.createClientWarningsPipeline).not.toHaveBeenCalled()
    })

    it('exposes a service descriptor whose id derives from the configured topic', () => {
        const consumer = createClientWarningsConsumer(
            { ...makeConfig(), INGESTION_CONSUMER_CONSUME_TOPIC: 'client_warnings' },
            makeDeps()
        )
        expect(consumer.service.id).toBe('ingestion-consumer-client_warnings')
    })
})
