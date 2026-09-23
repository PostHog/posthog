import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { projectLogic } from 'scenes/projectLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlResourceType } from '~/types'

import { logsAlertsList } from 'products/logs/frontend/generated/api'

import { alertsList } from '../generated/api'
import { hasEffectiveResourceAccess } from '../utils'

/**
 * Setup detection for the alerts empty state. The scene serves both alert kinds, so
 * either one counts as set up - a project alerting only on logs must not be told it
 * has no alerts. Each kind is queried only when the user can see its tab, because a
 * kind they cannot read would answer 403 and fail the whole check.
 */
export const alertsSetupLogic = createSetupDetectionLogic({
    productKey: ProductKey.ALERTS,
    path: ['products', 'alerts', 'frontend', 'emptyState', 'alertsSetupLogic'],
    detect: async () => {
        const canViewInsightAlerts = hasEffectiveResourceAccess(AccessControlResourceType.Insight)
        const canViewLogAlerts = hasEffectiveResourceAccess(AccessControlResourceType.Logs)
        if (!canViewInsightAlerts && !canViewLogAlerts) {
            // The scene renders its own access-denied screen, which the setup screen must not hide.
            return 'unknown'
        }

        const projectId = String(projectLogic.findMounted()?.values.currentProjectId)
        const [insightAlerts, logAlerts] = await Promise.all([
            canViewInsightAlerts ? alertsList(projectId, { limit: 1 }) : null,
            canViewLogAlerts ? logsAlertsList(projectId, { limit: 1 }) : null,
        ])
        const count = (insightAlerts?.count ?? 0) + (logAlerts?.count ?? 0)
        return count > 0 ? 'has-data' : 'needs-setup'
    },
})
