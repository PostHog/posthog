import { useActions, useValues } from 'kea'

import { IconChevronRight, IconDashboard, IconFolder } from '@posthog/icons'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { urls } from 'scenes/urls'

import { dashboardsModel } from '~/models/dashboardsModel'

import { dashboardsFileSystemLogic } from './dashboardsFileSystemLogic'
import { folderLabel } from './dashboardsFileSystemUtils'

// Finder arm (variant=finder): folder-first navigation. Opens at the dashboards root showing top-level
// folders; click a folder card to drill in, a breadcrumb crumb to climb back. Reuses the same FileSystem
// folder structure as the grid arm and the sidebar tree.
export function DashboardsFinder(): JSX.Element {
    const { currentFolderContents, breadcrumb } = useValues(dashboardsFileSystemLogic)
    const { navigateToFolder } = useActions(dashboardsFileSystemLogic)
    const { dashboardsLoading } = useValues(dashboardsModel)

    const isEmpty = currentFolderContents.subfolders.length === 0 && currentFolderContents.dashboards.length === 0
    if (dashboardsLoading && isEmpty) {
        return <Spinner className="text-2xl" />
    }

    return (
        <div className="flex flex-col gap-4" data-attr="dashboards-finder">
            <div className="flex items-center gap-1 flex-wrap" aria-label="Folder breadcrumb">
                {breadcrumb.map((crumb, index) => (
                    <span key={crumb.path} className="flex items-center gap-1">
                        {index > 0 ? <IconChevronRight className="text-muted" /> : null}
                        <button type="button" className="font-medium" onClick={() => navigateToFolder(crumb.path)}>
                            {crumb.label}
                        </button>
                    </span>
                ))}
            </div>
            <div className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-3">
                {currentFolderContents.subfolders.map((folder) => (
                    <button
                        key={folder}
                        type="button"
                        data-attr="dashboards-finder-folder"
                        onClick={() => navigateToFolder(folder)}
                    >
                        <LemonCard hoverEffect className="flex flex-col gap-1 h-full text-left">
                            <IconFolder className="text-2xl text-muted" />
                            <span className="font-semibold truncate">{folderLabel(folder)}</span>
                        </LemonCard>
                    </button>
                ))}
                {currentFolderContents.dashboards.map((dashboard) => (
                    <Link key={dashboard.id} to={urls.dashboard(dashboard.id)} data-attr="dashboards-finder-card">
                        <LemonCard hoverEffect className="flex flex-col gap-1 h-full">
                            <IconDashboard className="text-2xl text-muted" />
                            <span className="font-semibold truncate">{dashboard.name || 'Untitled'}</span>
                        </LemonCard>
                    </Link>
                ))}
            </div>
        </div>
    )
}
