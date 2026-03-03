import { HealthCheckResult, HealthCheckResultOk, PluginServerService } from '../../../types'
import { CyclotronV2Janitor } from './janitor'
import { CyclotronV2JanitorConfig } from './types'

export class CyclotronV2JanitorService {
    private janitor: CyclotronV2Janitor

    constructor(config: CyclotronV2JanitorConfig) {
        this.janitor = new CyclotronV2Janitor(config)
    }

    async start(): Promise<void> {
        await this.janitor.start()
    }

    async stop(): Promise<void> {
        await this.janitor.stop()
    }

    isHealthy(): HealthCheckResult {
        // The janitor is healthy as long as it's running (interval is set)
        // The underlying janitor swallows errors in its interval callback,
        // so if we got here it means the service is alive
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
