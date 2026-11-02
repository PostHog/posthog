import { HealthCheckResult, HealthCheckResultError, HealthCheckResultOk, PluginServerService } from '../../../types'
import { HogInvocationResultsService } from '../monitoring/hog-invocation-results.service'
import { CyclotronV2Janitor } from './janitor'
import { CYCLOTRON_JOBS_TABLE, CyclotronJobTable } from './tables'
import { CyclotronV2JanitorConfig } from './types'

export class CyclotronV2JanitorService {
    private janitor: CyclotronV2Janitor
    private readonly table: CyclotronJobTable

    constructor(config: CyclotronV2JanitorConfig, invocationResults?: HogInvocationResultsService) {
        this.janitor = new CyclotronV2Janitor(config, invocationResults)
        this.table = config.table ?? CYCLOTRON_JOBS_TABLE
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
            // Per table, because two janitors load in one process under isDevEnv().
            id:
                this.table === CYCLOTRON_JOBS_TABLE
                    ? 'cdp-cyclotron-v2-janitor'
                    : 'cdp-cyclotron-v2-janitor-transactional',
            onShutdown: async () => await this.stop(),
            healthcheck: () => this.isHealthy(),
        }
    }
}
