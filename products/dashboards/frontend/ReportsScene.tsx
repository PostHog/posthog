import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconChevronRight, IconFolderPlus, IconPlus, IconCheckbox } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ProjectTree } from '~/layout/panel-layout/ProjectTree/ProjectTree'
import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { projectTreeLogic } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { joinPath, splitPath, unescapePath } from '~/layout/panel-layout/ProjectTree/utils'
import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { reportsLogic } from './reportsLogic'

export const REPORTS_TREE_KEY = 'reports-files'

export const scene: SceneExport = { component: ReportsScene }

export function ReportsScene(): JSX.Element {
    const { searchParams } = useValues(router)
    const folder = typeof searchParams.folder === 'string' ? searchParams.folder.replace(/^\/+|\/+$/g, '') : ''
    const treeProps = { key: `${REPORTS_TREE_KEY}:${folder}`, root: `project://${folder}`, folderHref: urls.reports }
    const { createFolder, setSelectMode, loadFolder } = useActions(projectTreeLogic(treeProps))
    const { selectMode, fullFileSystemFiltered, searchTerm } = useValues(projectTreeLogic(treeProps))
    const { pendingLoaderLoading, pendingActions, folderStates, unfiledItemsLoading } = useValues(projectTreeDataLogic)
    const creatingFolder = pendingLoaderLoading || pendingActions.length > 0
    const folderState = folderStates[folder]
    const parts = splitPath(folder)
    const { createDashboard, createInsight } = useActions(reportsLogic({ folder }))
    const { dashboardCreationLoading } = useValues(reportsLogic({ folder }))

    return (
        <SceneContent className="h-full min-h-0 flex-1 overflow-hidden">
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                    <h1 className="m-0 text-2xl font-semibold">Custom dashboards</h1>
                    <p className="mt-1 mb-0 text-secondary">
                        Organize dashboards, insights, and supporting files in shared project folders.
                    </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <LemonButton to={urls.dashboards()} type="secondary" data-attr="reports-all-dashboards">
                        All dashboards
                    </LemonButton>
                    <LemonButton to={urls.reportsInsights()} type="secondary" data-attr="reports-all-insights">
                        All insights
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
                        ]}
                    >
                        <LemonButton
                            type="primary"
                            icon={<IconPlus />}
                            loading={dashboardCreationLoading}
                            data-attr="reports-new-report"
                        >
                            New
                        </LemonButton>
                    </LemonMenu>
                </div>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-2">
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
                                {unescapePath(part)}
                            </LemonButton>
                        </span>
                    ))}
                </nav>
                <div className="flex flex-wrap items-center gap-2">
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconCheckbox />}
                        active={selectMode === 'multi'}
                        onClick={() => setSelectMode(selectMode === 'multi' ? 'default' : 'multi')}
                        data-attr="reports-select-items"
                    >
                        {selectMode === 'multi' ? 'Done selecting' : 'Select items'}
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconFolderPlus />}
                        onClick={() => createFolder(folder)}
                        loading={creatingFolder}
                        disabledReason={
                            folderState === 'loading'
                                ? 'Folders are loading'
                                : folderState === 'error'
                                  ? 'Reload this folder before adding files'
                                  : undefined
                        }
                        data-attr="reports-new-folder"
                    >
                        New folder
                    </LemonButton>
                </div>
            </div>
            {folderState === 'error' && (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Retry',
                        onClick: () => loadFolder(folder),
                        loading: folderStates[folder] === 'loading',
                        'data-attr': 'reports-retry-folder',
                    }}
                >
                    Could not load this folder. Try again.
                </LemonBanner>
            )}
            {folderState === 'loaded' && !unfiledItemsLoading && !searchTerm && fullFileSystemFiltered.length === 0 && (
                <LemonBanner type="info">No files here yet. Create a folder or a report to get started.</LemonBanner>
            )}
            <div className="min-h-0 min-w-0 flex-1 overflow-hidden border rounded">
                <ProjectTree
                    key={folder}
                    layout="inline"
                    panelName="reports"
                    root={treeProps.root}
                    logicKey={treeProps.key}
                    folderHref={urls.reports}
                    searchPlaceholder="Search folders and files"
                    disableScroll={false}
                />
            </div>
        </SceneContent>
    )
}
