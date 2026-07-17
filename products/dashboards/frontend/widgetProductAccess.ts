import { userHasAccess } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { DashboardWidgetProductAccess } from './types'

const WIDGET_PRODUCT_ACCESS_CHECKS = {
    // New gated widget types: add a case here — CONTRIBUTING.md
    error_tracking: () => userHasAccess(AccessControlResourceType.ErrorTracking, AccessControlLevel.Viewer),
    session_recording: () => userHasAccess(AccessControlResourceType.SessionRecording, AccessControlLevel.Viewer),
    experiment: () => userHasAccess(AccessControlResourceType.Experiment, AccessControlLevel.Viewer),
    survey: () => userHasAccess(AccessControlResourceType.Survey, AccessControlLevel.Viewer),
    logs: () => userHasAccess(AccessControlResourceType.Logs, AccessControlLevel.Viewer),
} satisfies Record<DashboardWidgetProductAccess, () => boolean>

export function userHasDashboardWidgetProductAccess(productAccess: DashboardWidgetProductAccess | undefined): boolean {
    if (!productAccess) {
        return true
    }
    return WIDGET_PRODUCT_ACCESS_CHECKS[productAccess]()
}

/** In-tile issue row edits and assignee filter picker: dashboard editor or Error tracking editor. */
export function userCanMutateErrorTrackingIssuesOnDashboard(canEditDashboard: boolean): boolean {
    return canEditDashboard || userHasAccess(AccessControlResourceType.ErrorTracking, AccessControlLevel.Editor)
}
