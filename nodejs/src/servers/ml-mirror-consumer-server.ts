import { initializePrometheusLabels } from '~/common/api/router'

import { CleanupResources, NodeServer, ServerLifecycle } from './base-server'
import { IngestionSessionReplayMlMirrorServerConfig, buildMlMirrorServerConfig } from './ml-mirror-server-config'

export abstract class MlMirrorConsumerServer implements NodeServer {
    readonly lifecycle: ServerLifecycle
    protected readonly config: IngestionSessionReplayMlMirrorServerConfig
    /** Labels added to every metric of this pod, so a server that shares metric names with another can tell its series apart. */
    protected readonly metricLabels: Record<string, string> = {}

    constructor(config: Partial<IngestionSessionReplayMlMirrorServerConfig> = {}) {
        this.config = buildMlMirrorServerConfig(config)
        this.lifecycle = new ServerLifecycle(this.config)
    }

    async start(): Promise<void> {
        return this.lifecycle.start(
            () => {
                initializePrometheusLabels(
                    this.config.INGESTION_PIPELINE,
                    this.config.INGESTION_LANE,
                    this.metricLabels
                )
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
