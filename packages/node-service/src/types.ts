import type { Logger } from 'pino'

import type { ServiceMetrics } from './metrics.js'

export interface HealthCheckResult {
    status: 'ok' | 'error'
    message?: string
}

export type HealthCheck = () => HealthCheckResult | Promise<HealthCheckResult>

export interface ServiceState {
    ready: boolean
    shuttingDown: boolean
}

export interface ServiceBindings {
    logger: Logger
    metrics: ServiceMetrics
    state: ServiceState
}
