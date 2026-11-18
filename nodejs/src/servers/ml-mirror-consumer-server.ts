import { initializePrometheusLabels } from '~/common/api/router'

import { CleanupResources, NodeServer, ServerLifecycle } from './base-server'
import { IngestionSessionReplayMlMirrorServerConfig, buildMlMirrorServerConfig } from './ml-mirror-server-config'

export abstract class MlMirrorConsumerServer implements NodeServer {
    readonly lifecycle: ServerLifecycle
    protected readonly config: IngestionSessionReplayMlMirrorServerConfig

    constructor(config: Partial<IngestionSessionReplayMlMirrorServerConfig> = {}) {
        this.config = buildMlMirrorServerConfig(config)
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
