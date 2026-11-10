import {
    ActivityLogItem,
    ActivityLogUserName,
    Describer,
    HumanizedChange,
    activityLogSummary,
    defaultDescriber,
} from 'lib/components/ActivityLog/humanizeActivity'
import { Link } from 'lib/lemon-ui/Link'
import { addProjectIdIfMissing } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

function workloadTrustDescriber(
    verbs: Record<string, string>,
    targetUrl: (logItem: ActivityLogItem) => string | null
): Describer {
    return (logItem: ActivityLogItem): HumanizedChange => {
        const verb = verbs[logItem.activity]
        if (!verb) {
            return defaultDescriber(logItem)
        }
        const name = <strong>{logItem.detail?.name || 'a workload trust policy'}</strong>
        const url = targetUrl(logItem)
        // The organization audit log lists entries from every project, so links name the entry's own project.
        const target = url ? <Link to={addProjectIdIfMissing(url, logItem.team_id ?? undefined)}>{name}</Link> : name
        return {
            summary: activityLogSummary(logItem, `${verb} the workload trust policy`, target),
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> {verb} the workload trust policy {target}
                </>
            ),
        }
    }
}

export const workloadTrustPolicyActivityDescriber = workloadTrustDescriber(
    { created: 'created', updated: 'updated', deleted: 'deleted' },
    (logItem) => (logItem.activity === 'deleted' ? null : urls.settings('environment-trusted-workloads'))
)

export const workloadTrustPolicyRequestActivityDescriber = workloadTrustDescriber(
    { created: 'asked for', approved: 'approved', rejected: 'rejected' },
    (logItem) => (logItem.item_id ? urls.workloadTrustPolicyRequest(logItem.item_id) : null)
)
