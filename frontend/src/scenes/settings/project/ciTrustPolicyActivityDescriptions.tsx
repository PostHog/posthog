import {
    ActivityLogItem,
    ActivityLogUserName,
    Describer,
    HumanizedChange,
    activityLogSummary,
    defaultDescriber,
} from 'lib/components/ActivityLog/humanizeActivity'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

function ciTrustDescriber(
    verbs: Record<string, string>,
    targetUrl: (logItem: ActivityLogItem) => string | null
): Describer {
    return (logItem: ActivityLogItem): HumanizedChange => {
        const verb = verbs[logItem.activity]
        if (!verb) {
            return defaultDescriber(logItem)
        }
        const name = <strong>{logItem.detail?.name || 'a CI trust policy'}</strong>
        const url = targetUrl(logItem)
        const target = url ? <Link to={url}>{name}</Link> : name
        return {
            summary: activityLogSummary(logItem, `${verb} the CI trust policy`, target),
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> {verb} the CI trust policy {target}
                </>
            ),
        }
    }
}

export const ciTrustPolicyActivityDescriber = ciTrustDescriber(
    { created: 'created', updated: 'updated', deleted: 'deleted' },
    (logItem) => (logItem.activity === 'deleted' ? null : urls.settings('environment-ci-trust-policies'))
)

export const ciTrustPolicyRequestActivityDescriber = ciTrustDescriber(
    { created: 'asked for', approved: 'approved', rejected: 'rejected' },
    (logItem) => (logItem.item_id ? urls.ciTrustPolicyRequest(logItem.item_id) : null)
)
