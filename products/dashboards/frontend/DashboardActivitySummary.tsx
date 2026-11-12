import { useActions, useValues } from 'kea'

import { IconPulse } from '@posthog/icons'
import { Spinner, Tooltip } from '@posthog/lemon-ui'

import { activityClientLabel } from 'lib/components/ActivityLog/activityClientLabel'
import { dayjs } from 'lib/dayjs'
import { fullNameOrEmail } from 'lib/utils/strings'

import type { UserBasicType } from '~/types'

import { dashboardActivitySummaryLogic } from './dashboardActivitySummaryLogic'
import type { DashboardActivitySummaryApi, UserBasicApi } from './generated/api.schemas'

function byUser(user: UserBasicType | UserBasicApi | null | undefined): string {
    return user ? ` by ${fullNameOrEmail(user)}` : ''
}

function SummaryContent({
    createdAt,
    createdBy,
    summary,
}: {
    createdAt: string
    createdBy: UserBasicType | null
    summary: DashboardActivitySummaryApi
}): JSX.Element {
    return (
        <ul className="flex flex-col gap-1 py-1">
            <li>
                Created {dayjs(createdAt).fromNow()}
                {byUser(createdBy)}
            </li>
            <li>
                {summary.last_edited_at ? (
                    <>
                        Edited {dayjs(summary.last_edited_at).fromNow()}
                        {byUser(summary.last_edited_by)}
                        {summary.last_edited_client ? ` via ${activityClientLabel(summary.last_edited_client)}` : ''}
                    </>
                ) : (
                    'No edits logged'
                )}
            </li>
            <li>
                {summary.last_viewed_by_others_at ? (
                    <>
                        Last viewed by others:{' '}
                        {summary.last_viewed_by_others_user
                            ? `${fullNameOrEmail(summary.last_viewed_by_others_user)}, `
                            : ''}
                        {dayjs(summary.last_viewed_by_others_at).fromNow()}
                    </>
                ) : (
                    'No one else has viewed it'
                )}
            </li>
            <li>
                {summary.recent_viewer_count === 1 ? '1 person' : `${summary.recent_viewer_count} people`} viewed it in
                the last 30 days
            </li>
            <li className="text-xs opacity-75">Refreshes, API reads and subscriptions are not counted.</li>
        </ul>
    )
}

/** Hover card that answers "is anyone still using this dashboard?", which the last refresh time does not. */
export function DashboardActivitySummary({
    dashboardId,
    createdAt,
    createdBy,
}: {
    dashboardId: number
    createdAt: string
    createdBy: UserBasicType | null
}): JSX.Element {
    const logic = dashboardActivitySummaryLogic({ dashboardId })
    const { activitySummary, activitySummaryLoading } = useValues(logic)
    const { loadActivitySummary } = useActions(logic)

    return (
        <Tooltip
            openOnClick
            onOpen={() => {
                if (!activitySummary && !activitySummaryLoading) {
                    loadActivitySummary()
                }
            }}
            title={
                activitySummary ? (
                    <SummaryContent createdAt={createdAt} createdBy={createdBy} summary={activitySummary} />
                ) : (
                    <Spinner textColored />
                )
            }
        >
            <span
                className="inline-flex items-center text-muted text-base cursor-default"
                aria-label="Dashboard activity"
                data-attr="dashboard-activity-summary"
            >
                <IconPulse />
            </span>
        </Tooltip>
    )
}
