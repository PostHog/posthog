import { QuotaResource } from '../../common/services/quota-limiting.service'
import { HogFunctionMonitoringService } from '../services/monitoring/hog-function-monitoring.service'
import { CyclotronJobInvocationHogFunction } from '../types'
import { counterQuotaLimited } from './metrics'

export interface QuotaLimitingContext {
    hub: {
        quotaLimiting: {
            isTeamQuotaLimited: (teamId: number, resource: QuotaResource) => Promise<boolean>
        }
    }
    hogFunctionMonitoringService: HogFunctionMonitoringService
}

/**
 * Checks if an invocation should be quota limited and handles the appropriate metrics.
 * Returns true if the invocation should be blocked, false otherwise.
 */
export async function shouldBlockInvocationDueToQuota(
    item: CyclotronJobInvocationHogFunction,
    context: QuotaLimitingContext
): Promise<boolean> {
    const isQuotaLimited = await context.hub.quotaLimiting.isTeamQuotaLimited(item.teamId, 'cdp_trigger_events')

    if (isQuotaLimited) {
        counterQuotaLimited.labels({ team_id: item.teamId }).inc()

        context.hogFunctionMonitoringService.queueAppMetric(
            {
                team_id: item.teamId,
                app_source_id: item.functionId,
                metric_kind: 'failure',
                metric_name: 'quota_limited',
                count: 1,
            },
            'hog_function'
        )
        return true
    }

    return false
}
