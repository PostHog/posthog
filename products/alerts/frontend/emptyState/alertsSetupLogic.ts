import { ApiError } from 'lib/api-error'
import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { projectLogic } from 'scenes/projectLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlResourceType } from '~/types'

import { logsAlertsList } from 'products/logs/frontend/generated/api'

import { alertsList } from '../generated/api'
import { hasEffectiveResourceAccess } from '../utils'

// The frontend access check can pass while the backend still answers 403. Treat that kind as unreadable.
async function countUnlessForbidden(request: Promise<{ count: number }>): Promise<number | null> {
    try {
        return (await request).count
    } catch (error) {
        if (error instanceof ApiError && error.status === 403) {
            return null
        }
        throw error
    }
}

/**
 * Setup detection for the alerts empty state. The scene serves both alert kinds, so
 * either one counts as set up - a project alerting only on logs must not be told it
 * has no alerts. Each kind is queried only when the user can see its tab, because a
 * kind they cannot read would answer 403 and fail the whole check.
 */
export const alertsSetupLogic = createSetupDetectionLogic({
    productKey: ProductKey.ALERTS,
    path: ['products', 'alerts', 'frontend', 'emptyState', 'alertsSetupLogic'],
    cacheHasData: true,
    revalidateCachedHasData: true,
    detect: async () => {
        const canViewInsightAlerts = hasEffectiveResourceAccess(AccessControlResourceType.Insight)
        const canViewLogAlerts = hasEffectiveResourceAccess(AccessControlResourceType.Logs)
        if (!canViewInsightAlerts && !canViewLogAlerts) {
            // The scene renders its own access-denied screen, which the setup screen must not hide.
            return 'unknown'
        }

        const projectId = String(projectLogic.findMounted()?.values.currentProjectId)
        const counts = await Promise.all([
            canViewInsightAlerts ? countUnlessForbidden(alertsList(projectId, { limit: 1 })) : null,
            canViewLogAlerts ? countUnlessForbidden(logsAlertsList(projectId, { limit: 1 })) : null,
        ])
        const readableCounts = counts.filter((count): count is number => count !== null)
        if (readableCounts.length === 0) {
            return 'unknown'
        }
        return readableCounts.some((count) => count > 0) ? 'has-data' : 'needs-setup'
    },
})
