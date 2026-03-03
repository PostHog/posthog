import { HealthCheckResult, HealthCheckResultError, HealthCheckResultOk, PluginServerService } from '../../../types'
import { CyclotronV2Janitor } from './janitor'
import { CyclotronV2JanitorConfig } from './types'

export class CyclotronV2JanitorService {
    private janitor: CyclotronV2Janitor

    constructor(config: CyclotronV2JanitorConfig) {
        this.janitor = new CyclotronV2Janitor(config)
    }

    async start(): Promise<void> {
        // Validates the DB connection and starts the cleanup interval
        await this.janitor.start()
    }

    async stop(): Promise<void> {
        await this.janitor.stop()
    }

    isHealthy(): HealthCheckResult {
        if (!this.janitor.isRunning()) {
            return new HealthCheckResultError('CyclotronV2Janitor interval is not running', {})
        }
        return new HealthCheckResultOk()
    }

    get service(): PluginServerService {
        return {
            id: 'cdp-cyclotron-v2-janitor',
            onShutdown: async () => await this.stop(),
            healthcheck: () => this.isHealthy(),
        }
    }
}
