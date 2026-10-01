import { Link } from '@posthog/lemon-ui'

import {
    ActivityChange,
    ActivityLogItem,
    ActivityLogSummary,
    ActivityLogUserName,
    ChangeMapping,
    Description,
    HumanizedChange,
    defaultDescriber,
    detectBoolean,
} from 'lib/components/ActivityLog/humanizeActivity'
import { urls } from 'scenes/urls'

function nameAndLink(logItem?: ActivityLogItem): JSX.Element {
    return logItem?.item_id ? (
        <Link to={urls.crossProjectDashboard(String(logItem.item_id))}>
            {logItem?.detail?.name || 'Unknown dashboard'}
        </Link>
    ) : logItem?.detail?.name ? (
        <>{logItem.detail.name}</>
    ) : (
        <i>Unknown dashboard</i>
    )
}

function summaryFor(logItem: ActivityLogItem, action: Description): ActivityLogSummary {
    return {
        actor: <ActivityLogUserName logItem={logItem} />,
        action,
        target: <>Cross-project dashboard · {nameAndLink(logItem)}</>,
    }
}

const FIELD_DESCRIBERS: Record<string, (change: ActivityChange, logItem: ActivityLogItem) => ChangeMapping | null> = {
    name: (change, logItem) => ({
        description: [
            <>
                renamed "{String(change.before)}" to <strong>"{nameAndLink(logItem)}"</strong>
            </>,
        ],
        summary: [
            <>
                renamed "{String(change.before)}" to "{String(change.after)}"
            </>,
        ],
        suffix: <></>,
    }),
    description: (_change, logItem) => ({
        description: [<>changed the description of</>],
        summary: [<>changed the description</>],
        suffix: <>{nameAndLink(logItem)}</>,
    }),
    filters: (_change, logItem) => ({
        description: [<>changed the filters on</>],
        summary: [<>changed the filters</>],
        suffix: <>{nameAndLink(logItem)}</>,
    }),
    deleted: (change, logItem) => {
        const action = detectBoolean(change.after) ? 'deleted' : 'restored'
        return {
            description: [<>{action}</>],
            summary: [<>{action} the dashboard</>],
            suffix: <>{nameAndLink(logItem)}</>,
        }
    },
}

export function crossProjectDashboardActivityDescriber(
    logItem: ActivityLogItem,
    asNotification?: boolean
): HumanizedChange {
    if (logItem.scope !== 'CrossProjectDashboard') {
        console.error('cross-project dashboard describer received a non-dashboard activity')
        return { description: null }
    }

    if (logItem.activity === 'created') {
        return {
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> created the cross-project dashboard {nameAndLink(logItem)}
                </>
            ),
            summary: summaryFor(logItem, <>created</>),
        }
    }

    if (logItem.activity === 'deleted') {
        return {
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> deleted the cross-project dashboard {logItem.detail.name}
                </>
            ),
            summary: summaryFor(logItem, <>deleted</>),
        }
    }

    if (logItem.activity === 'updated') {
        const descriptions: Description[] = []
        const summaries: Description[] = []
        let suffix: Description | undefined

        for (const change of logItem.detail.changes ?? []) {
            const describe = change.field ? FIELD_DESCRIBERS[change.field] : undefined
            const mapping = describe?.(change, logItem)
            if (!mapping?.description) {
                continue
            }
            descriptions.push(...mapping.description)
            summaries.push(...(mapping.summary ?? mapping.description))
            suffix = mapping.suffix
        }

        if (descriptions.length === 0) {
            return defaultDescriber(logItem, asNotification)
        }

        return {
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> {descriptions} {suffix}
                </>
            ),
            summary: summaryFor(logItem, <>{summaries}</>),
        }
    }

    return defaultDescriber(logItem, asNotification)
}
