import { initializePrometheusLabels } from '~/common/api/router'
import {
    AiResearchV4ServerConfig,
    buildAiResearchV4ServerConfig,
} from '~/ingestion/pipelines/sessionreplay/ai-research/config'
import { CleanupResources, NodeServer, ServerLifecycle } from '~/servers/base-server'

/** The lifecycle every v4 Kafka consumer server shares: the HTTP server, metric labels, start and stop. */
export abstract class AiResearchV4ConsumerServer implements NodeServer {
    readonly lifecycle: ServerLifecycle
    protected readonly config: AiResearchV4ServerConfig

    constructor(config: Partial<AiResearchV4ServerConfig> = {}) {
        this.config = buildAiResearchV4ServerConfig(config)
        this.lifecycle = new ServerLifecycle(this.config)
    }

    async start(): Promise<void> {
        return this.lifecycle.start(
            () => {
                initializePrometheusLabels(this.config.INGESTION_PIPELINE, this.config.INGESTION_LANE)
                return this.startServices()
            },
            () => this.getCleanupResources()
        )
    }

    async stop(error?: Error): Promise<void> {
        return this.lifecycle.stop(() => this.getCleanupResources(), error)
    }

    protected abstract startServices(): Promise<void>
    protected abstract getCleanupResources(): CleanupResources
}
