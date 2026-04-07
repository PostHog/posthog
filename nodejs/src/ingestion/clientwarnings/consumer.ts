import { PluginServerService } from '../../types'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { TeamManager } from '../../utils/team-manager'
import { CommonIngestionConsumer, CommonIngestionConsumerConfig } from '../common/common-ingestion-consumer'
import { DlqOutput, IngestionWarningsOutput } from '../common/outputs'
import { IngestionConsumerConfig } from '../config'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { createClientWarningsPipeline } from './pipeline'

export interface ClientWarningsConsumerDeps {
    outputs: IngestionOutputs<IngestionWarningsOutput | DlqOutput>
    teamManager: TeamManager
}

export class ClientWarningsConsumer {
    private consumer: CommonIngestionConsumer

    constructor(
        config: CommonIngestionConsumerConfig,
        deps: ClientWarningsConsumerDeps,
        overrides?: Partial<
            Pick<IngestionConsumerConfig, 'INGESTION_CONSUMER_GROUP_ID' | 'INGESTION_CONSUMER_CONSUME_TOPIC'>
        >
    ) {
        const promiseScheduler = new PromiseScheduler()

        const pipeline = createClientWarningsPipeline({
            outputs: deps.outputs,
            teamManager: deps.teamManager,
            promiseScheduler,
        })

        this.consumer = new CommonIngestionConsumer(
            config,
            pipeline,
            {
                onStart: async () => {
                    const topicFailures = await deps.outputs.checkTopics()
                    if (topicFailures.length > 0) {
                        throw new Error(`Output topic verification failed for: ${topicFailures.join(', ')}`)
                    }
                },
            },
            overrides
        )
    }

    get service(): PluginServerService {
        return this.consumer.service
    }

    async start(): Promise<void> {
        return this.consumer.start()
    }

    async stop(): Promise<void> {
        return this.consumer.stop()
    }
}
