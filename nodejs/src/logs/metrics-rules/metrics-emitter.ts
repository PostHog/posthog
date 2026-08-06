import { Counter } from 'prom-client'

import { logger } from '~/common/utils/logger'
import { internalFetch } from '~/common/utils/request'

export const logsMetricRulesExportFailedCounter = new Counter({
    name: 'logs_metrics_rules_export_failed_total',
    help: 'OTLP export of log-generated metrics failed after retry; the flush window was dropped.',
    labelNames: ['team_id'],
})

const EXPORT_ATTEMPTS = 2

/**
 * POSTs log-generated metric payloads to the capture-logs OTLP metrics endpoint using
 * the team's own token, so the generated series flows through the exact same pipeline
 * (fingerprinting, quota, Kafka, ClickHouse) as customer-sent metrics.
 *
 * Best-effort by design: one retry, then the window's aggregates are dropped with a
 * counter — metric emission must never buffer unboundedly or block log ingestion.
 */
export class LogsMetricsEmitter {
    constructor(private readonly url: string) {}

    public async emit(token: string, teamId: number, payload: Record<string, unknown>): Promise<boolean> {
        const body = JSON.stringify(payload)
        for (let attempt = 1; attempt <= EXPORT_ATTEMPTS; attempt++) {
            try {
                const response = await internalFetch(this.url, {
                    method: 'POST',
                    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
                    body,
                })
                await response.dump()
                if (response.status >= 200 && response.status < 300) {
                    return true
                }
                logger.warn('[logs-metric-rules] OTLP export rejected', {
                    teamId,
                    status: response.status,
                    attempt,
                })
            } catch (error) {
                logger.warn('[logs-metric-rules] OTLP export failed', { teamId, error: String(error), attempt })
            }
        }
        logsMetricRulesExportFailedCounter.inc({ team_id: String(teamId) })
        return false
    }
}
