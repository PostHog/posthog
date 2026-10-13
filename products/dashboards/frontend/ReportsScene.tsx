import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconChevronRight, IconFolderPlus, IconPeople, IconPin, IconPinFilled, IconPlus } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCard,
    LemonInput,
    LemonMenu,
    LemonSelect,
    LemonSkeleton,
    LemonTag,
} from '@posthog/lemon-ui'

import { getCurrentTeamIdOrNone } from 'lib/utils/getAppContext'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { joinPath, parentPath, splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { ReportFilesTable } from './ReportFilesTable'
import { ReportFolderCard } from './ReportFolderCard'
import { getReportFolderContext } from './reportFolderContext'
import { ReportFolderSetupModal } from './ReportFolderSetupModal'
import { reportsLogic } from './reportsLogic'

export const scene: SceneExport = { component: ReportsScene }

export function ReportsScene(): JSX.Element {
    const { searchParams } = useValues(router)
    const folder = typeof searchParams.folder === 'string' ? joinPath(splitPath(searchParams.folder)) : ''
    const { currentTeamId } = useValues(teamLogic)
    const teamId = currentTeamId ?? getCurrentTeamIdOrNone()
    const logic = reportsLogic({ folder, teamId })
    const {
        createDashboard,
        createInsight,
        openFolderSetup,
        setSearchTerm,
        setFileType,
        loadFolder,
        loadSearchResults,
    } = useActions(logic)
    const {
        dashboardCreationLoading,
        dashboardsLoading,
        currentFolder,
        folderContext,
        pinnedDashboard,
        nameSortedDashboards,
        folderEntries,
        entries,
        searchTerm,
        fileType,
        searchResultsLoading,
        searchResults,
        savedContextLoading,
        isFolderFormSubmitting,
    } = useValues(logic)
    const { folderStates } = useValues(projectTreeDataLogic)
    const folderState = folderStates[folder]
    const loading = !folderState || (folderState === 'loading' && entries.length === 0)
    const folderUnavailable = !!folder && !currentFolder && folderStates[parentPath(folder)] === 'loaded'
    const parts = splitPath(folder)
    const canEditFolder = !!currentFolder && !savedContextLoading && !isFolderFormSubmitting

    return (
        <SceneContent className="@container/reports min-h-0 flex-1 overflow-y-auto">
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                    <h1 className="m-0 text-2xl font-semibold">Custom dashboards</h1>
                    <p className="mt-1 mb-0 text-secondary">
                        A shared home for your teams’ dashboards, insights, and notes.
                    </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <LemonButton to={urls.dashboards()} type="secondary" data-attr="reports-all-dashboards">
                        All dashboards
                    </LemonButton>
                    <LemonButton to={urls.reportsInsights()} type="secondary" data-attr="reports-all-insights">
                        All insights
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        icon={<IconPeople />}
                        onClick={() => openFolderSetup(true)}
                        disabledReason={folderUnavailable ? 'Return to All folders to create a folder' : undefined}
                        data-attr="reports-create-team-folder"
                    >
                        New team folder
                    </LemonButton>
                    <LemonMenu
                        items={[
                            {
                                label: 'Dashboard',
                                onClick: createDashboard,
                                disabledReason: dashboardCreationLoading ? 'Creating a dashboard' : undefined,
                                'data-attr': 'reports-new-dashboard',
                            },
                            { label: 'Insight', onClick: createInsight, 'data-attr': 'reports-new-insight' },
                            {
                                label: 'Folder',
                                onClick: () => openFolderSetup(false),
                                'data-attr': 'reports-new-folder',
                            },
                        ]}
                    >
                        <LemonButton
                            type="primary"
                            icon={<IconPlus />}
                            loading={dashboardCreationLoading}
                            disabledReason={folderUnavailable ? 'Return to All folders to create a file' : undefined}
                            data-attr="reports-new-report"
                        >
                            New
                        </LemonButton>
                    </LemonMenu>
                </div>
            </div>
            <nav aria-label="Report folders" className="flex min-w-0 flex-wrap items-center gap-1">
                <LemonButton size="small" to={urls.reports()} active={!folder} data-attr="reports-root-folder">
                    All folders
                </LemonButton>
                {parts.map((part, index) => (
                    <span key={index} className="flex min-w-0 items-center gap-1">
                        <IconChevronRight className="text-secondary shrink-0" />
                        <LemonButton
                            size="small"
                            to={urls.reports(joinPath(parts.slice(0, index + 1)))}
                            active={index === parts.length - 1}
                            data-attr="reports-folder-breadcrumb"
                        >
                            {part}
                        </LemonButton>
                    </span>
                ))}
            </nav>
            {folder && !currentFolder && folderStates[parentPath(folder)] === 'error' && (
                <LemonBanner
                    type="error"
                    action={{ children: 'Retry', onClick: () => loadFolder(parentPath(folder), true) }}
                >
                    Could not load this folder’s details. Try again.
                </LemonBanner>
            )}
            {folderState === 'error' ? (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Retry',
                        onClick: () => loadFolder(folder, true),
                        'data-attr': 'reports-retry-folder',
                    }}
                >
                    Could not load this folder. Try again.
                </LemonBanner>
            ) : folderUnavailable ? (
                <LemonBanner type="warning" action={{ children: 'All folders', to: urls.reports() }}>
                    Could not find this folder. It may have been moved or deleted.
                </LemonBanner>
            ) : loading ? (
                <LemonSkeleton className="h-40" />
            ) : (
                <>
                    {!folder &&
                        !searchTerm &&
                        !folderEntries.some((entry) => getReportFolderContext(entry).team_folder) && (
                            <LemonCard hoverEffect={false} className="!p-5">
                                <div className="flex flex-wrap items-start justify-between gap-4">
                                    <div className="min-w-0">
                                        <h2 className="text-lg m-0">Give your team a place to start</h2>
                                        <p className="text-secondary mt-1 mb-0">
                                            Keep the analysis that matters together, and make the team’s main dashboard
                                            easy to find.
                                        </p>
                                    </div>
                                    <LemonButton
                                        type="primary"
                                        icon={<IconFolderPlus />}
                                        onClick={() => openFolderSetup(true)}
                                        data-attr="reports-setup-team"
                                    >
                                        Set up a team folder
                                    </LemonButton>
                                </div>
                                <ol className="grid grid-cols-1 @min-[48rem]/reports:grid-cols-3 gap-4 mt-5 mb-0 pl-5 text-secondary">
                                    <li>
                                        <strong className="text-primary">Name your team folder</strong>
                                        <p className="text-sm mt-1 mb-0">Organize by team, project, or goal.</p>
                                    </li>
                                    <li>
                                        <strong className="text-primary">Pin a starting dashboard</strong>
                                        <p className="text-sm mt-1 mb-0">Give everyone a clear place to begin.</p>
                                    </li>
                                    <li>
                                        <strong className="text-primary">Bring related work together</strong>
                                        <p className="text-sm mt-1 mb-0">
                                            Add insights and notes alongside dashboards.
                                        </p>
                                    </li>
                                </ol>
                            </LemonCard>
                        )}
                    {folder && !searchTerm && (
                        <LemonCard hoverEffect={false} className="!p-5 flex flex-col gap-4">
                            <div className="flex flex-wrap items-start justify-between gap-3">
                                <div className="min-w-0">
                                    <div className="flex flex-wrap items-center gap-2">
                                        <h2 className="text-xl m-0 min-w-0 max-w-full break-words">{parts.at(-1)}</h2>
                                        {folderContext.team_folder && <LemonTag>Team folder</LemonTag>}
                                    </div>
                                    <p className="text-secondary mt-1 mb-0 break-words">
                                        {folderContext.description ||
                                            'Keep this team’s dashboards, insights, and notes together.'}
                                    </p>
                                </div>
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    onClick={() => openFolderSetup(folderContext.team_folder, currentFolder ?? null)}
                                    disabledReason={canEditFolder ? undefined : 'Loading folder details'}
                                    data-attr="reports-edit-folder"
                                >
                                    Edit folder details
                                </LemonButton>
                            </div>
                            <div className="border-t pt-4 flex flex-wrap items-center justify-between gap-3">
                                <div className="min-w-0">
                                    <div className="text-xs text-secondary flex items-center gap-1 mb-1">
                                        <IconPinFilled />
                                        <span>{folderContext.team_folder ? 'Team dashboard' : 'Pinned dashboard'}</span>
                                    </div>
                                    <strong className="break-words">
                                        {pinnedDashboard?.name ||
                                            (folderContext.pinned_dashboard_id
                                                ? dashboardsLoading
                                                    ? 'Loading dashboard'
                                                    : 'Pinned dashboard unavailable'
                                                : 'Choose a dashboard for your team')}
                                    </strong>
                                    <p className="text-secondary text-sm mt-1 mb-0">
                                        {pinnedDashboard
                                            ? 'Start here, then explore the related analysis below.'
                                            : 'Pin an existing dashboard, or create one in this folder.'}
                                    </p>
                                </div>
                                <div className="flex flex-wrap items-center gap-2">
                                    {pinnedDashboard && (
                                        <LemonButton
                                            type="primary"
                                            to={urls.dashboard(pinnedDashboard.id)}
                                            data-attr="reports-open-pinned-dashboard"
                                        >
                                            Open dashboard
                                        </LemonButton>
                                    )}
                                    <LemonButton
                                        type={pinnedDashboard ? 'secondary' : 'primary'}
                                        icon={<IconPin />}
                                        onClick={() =>
                                            openFolderSetup(folderContext.team_folder, currentFolder ?? null)
                                        }
                                        disabledReason={canEditFolder ? undefined : 'Loading folder details'}
                                        data-attr="reports-choose-pinned-dashboard"
                                    >
                                        {pinnedDashboard ? 'Change' : 'Choose dashboard'}
                                    </LemonButton>
                                    {!pinnedDashboard && (
                                        <LemonButton
                                            type="secondary"
                                            onClick={createDashboard}
                                            loading={dashboardCreationLoading}
                                        >
                                            Create dashboard
                                        </LemonButton>
                                    )}
                                </div>
                            </div>
                        </LemonCard>
                    )}
                    <div className="flex flex-wrap items-center gap-2">
                        <LemonInput
                            type="search"
                            value={searchTerm}
                            onChange={setSearchTerm}
                            placeholder="Search folders and files"
                            className="flex-1 min-w-48"
                            data-attr="reports-search"
                        />
                        <LemonSelect
                            value={fileType}
                            onChange={setFileType}
                            options={[
                                { value: 'all', label: 'All file types' },
                                { value: 'dashboard', label: 'Dashboards' },
                                { value: 'insight', label: 'Insights' },
                                { value: 'notebook', label: 'Notebooks' },
                            ]}
                        />
                    </div>
                    {folderEntries.length > 0 && (
                        <section>
                            <div className="flex items-center justify-between gap-2 mb-3">
                                <h2 className="text-base m-0">{folder ? 'Folders' : 'Teams and folders'}</h2>
                                <LemonButton
                                    size="small"
                                    icon={<IconFolderPlus />}
                                    onClick={() => openFolderSetup(false)}
                                >
                                    New folder
                                </LemonButton>
                            </div>
                            <div className="grid grid-cols-1 @min-[40rem]/reports:grid-cols-2 @min-[64rem]/reports:grid-cols-3 gap-3">
                                {folderEntries.map((entry) => (
                                    <ReportFolderCard
                                        key={entry.id}
                                        entry={entry}
                                        dashboardLoading={dashboardsLoading}
                                        dashboard={nameSortedDashboards.find(
                                            (dashboard) =>
                                                dashboard.id === getReportFolderContext(entry).pinned_dashboard_id
                                        )}
                                    />
                                ))}
                            </div>
                        </section>
                    )}
                    {(folder ||
                        searchTerm ||
                        fileType !== 'all' ||
                        entries.some((entry) => entry.type !== 'folder')) && (
                        <section className="min-w-0">
                            <h2 className="text-base mt-0 mb-3">
                                {searchTerm ? 'Matching files' : folder ? 'Files in this folder' : 'Files'}
                            </h2>
                            <ReportFilesTable
                                folder={folder}
                                teamId={teamId}
                                loading={searchResultsLoading || folderState === 'loading'}
                            />
                        </section>
                    )}
                    {folderState === 'has-more' && !searchTerm && (
                        <LemonButton type="secondary" onClick={() => loadFolder(folder)} data-attr="reports-load-more">
                            Load more folders and files
                        </LemonButton>
                    )}
                    {searchTerm && searchResults.hasMore && (
                        <LemonButton
                            type="secondary"
                            onClick={() => loadSearchResults(searchTerm, searchResults.results.length)}
                            loading={searchResultsLoading}
                        >
                            Load more results
                        </LemonButton>
                    )}
                </>
            )}
            <ReportFolderSetupModal folder={folder} teamId={teamId} />
        </SceneContent>
    )
}
