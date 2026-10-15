import { IconFolder, IconPeople, IconPinFilled } from '@posthog/icons'
import { LemonButton, LemonCard, LemonTag } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import type { DashboardBasicApi } from './generated/api.schemas'
import { getReportFolderContext } from './reportFolderContext'

export function ReportFolderCard({
    entry,
    dashboard,
    dashboardLoading,
}: {
    entry: FileSystemEntry
    dashboard?: DashboardBasicApi
    dashboardLoading: boolean
}): JSX.Element {
    const context = getReportFolderContext(entry)
    const name = splitPath(entry.path).at(-1) || 'Untitled folder'
    return (
        <LemonCard hoverEffect={false} className="!p-4 min-w-0 flex flex-col gap-3">
            <div className="flex items-center gap-2 min-w-0">
                {context.team_folder ? (
                    <IconPeople className="text-secondary text-xl shrink-0" />
                ) : (
                    <IconFolder className="text-secondary text-xl shrink-0" />
                )}
                <div className="flex-1 min-w-0">
                    <LemonButton
                        to={urls.reports(entry.path)}
                        fullWidth
                        className="min-w-0"
                        data-attr="reports-open-folder"
                    >
                        {name}
                    </LemonButton>
                </div>
                {context.team_folder && <LemonTag className="shrink-0">Team</LemonTag>}
            </div>
            <p className="text-secondary text-sm m-0 line-clamp-2 break-words">
                {context.description ||
                    (context.team_folder
                        ? 'A shared home for this team’s analysis.'
                        : 'Dashboards, insights, and notes.')}
            </p>
            <div className="mt-auto border-t pt-3 min-w-0">
                {dashboard ? (
                    <LemonButton
                        icon={<IconPinFilled />}
                        to={urls.dashboard(dashboard.id)}
                        fullWidth
                        size="small"
                        data-attr="reports-open-pinned-dashboard"
                    >
                        {dashboard.name || 'Untitled dashboard'}
                    </LemonButton>
                ) : (
                    <span className="text-secondary text-xs">
                        {context.pinned_dashboard_id
                            ? dashboardLoading
                                ? 'Loading dashboard'
                                : 'Pinned dashboard unavailable'
                            : 'Open folder to choose a starting dashboard'}
                    </span>
                )}
            </div>
        </LemonCard>
    )
}
