import { useActions, useValues } from 'kea'

import { IconFolder, IconHome, IconLock, IconPin, IconPinFilled, IconShare } from '@posthog/icons'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { BulkUpdateTagsButton } from 'lib/components/BulkActions/BulkUpdateTagsButton'
import { moveToLogic } from 'lib/components/FileSystem/MoveTo/moveToLogic'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonRow } from 'lib/lemon-ui/LemonRow'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { atColumn, createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { accessLevelSatisfied } from 'lib/utils/accessControlUtils'
import { DashboardEventSource, eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { dashboardsLogic } from 'scenes/dashboard/dashboards/dashboardsLogic'
import { deleteDashboardLogic } from 'scenes/dashboard/deleteDashboardLogic'
import { duplicateDashboardLogic } from 'scenes/dashboard/duplicateDashboardLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { dashboardsModel, nameCompareFunction } from '~/models/dashboardsModel'
import { FileSystemEntry } from '~/queries/schema/schema-general'
import {
    AccessControlLevel,
    AccessControlResourceType,
    DashboardBasicType,
    DashboardMode,
    DashboardType,
} from '~/types'

import { UNFILED_DASHBOARDS_FOLDER } from '../dashboardConstants'
import { DASHBOARD_CANNOT_EDIT_MESSAGE } from '../DashboardHeader'
import { DashboardsFiltersBar } from './DashboardsFiltersBar'

export function DashboardsTableContainer(): JSX.Element {
    const { dashboardsLoading } = useValues(dashboardsModel)
    const { dashboards } = useValues(dashboardsLogic)

    return <DashboardsTable dashboards={dashboards} dashboardsLoading={dashboardsLoading} />
}

interface DashboardsTableProps {
    dashboards: DashboardBasicType[]
    dashboardsLoading: boolean
    extraActions?: JSX.Element | JSX.Element[]
    hideActions?: boolean
    // Tree arm: resolves a dashboard's FileSystem entry for "Move to another folder". The sidebar-backed
    // itemsByRef only holds lazily-loaded folders, so it's missing for most dashboards (the Move action then
    // never appears). The tree arm passes its complete entryByRef so every dashboard is movable.
    dashboardFsEntry?: (id: number) => FileSystemEntry | undefined
}

export function DashboardsTable({
    dashboards,
    dashboardsLoading,
    extraActions,
    hideActions,
    dashboardFsEntry,
}: DashboardsTableProps): JSX.Element {
    const { unpinDashboard, pinDashboard } = useActions(dashboardsModel)
    const { tableSortingChanged, setFilters } = useActions(dashboardsLogic)
    const { tableSorting, filters } = useValues(dashboardsLogic)
    // Server-side fuzzy search ranks results by relevance; re-sorting alphabetically by name
    // would push the exact match below partial matches. Suppress the persisted column sort
    // while the user has an active search term.
    const effectiveTableSorting = filters.search ? null : tableSorting
    const { currentTeam } = useValues(teamLogic)
    const { showDuplicateDashboardModal } = useActions(duplicateDashboardLogic)
    const { showDeleteDashboardModal } = useActions(deleteDashboardLogic)
    const { openMoveToModal } = useActions(moveToLogic)
    const { reportDashboardMoveInitiated } = useActions(eventUsageLogic)
    const { itemsByRef } = useValues(projectTreeDataLogic)

    // Prefer the tree arm's complete entryByRef over the sidebar's lazily-loaded itemsByRef, so every
    // dashboard is movable even before the sidebar has populated.
    const fsEntryFor = (id: number): FileSystemEntry | undefined =>
        dashboardFsEntry?.(id) ?? itemsByRef[`dashboard::${id}`]

    // The tree arm is the only caller that supplies a complete entry source. Control falls back to the
    // sidebar's lazily-loaded itemsByRef, which is mostly empty here — so the bulk "Move to folder" button
    // would render perpetually disabled. Gate it on the tree arm so control's bulk bar is unchanged.
    const isTreeArm = !!dashboardFsEntry

    const columns: LemonTableColumns<DashboardType> = [
        {
            width: 0,
            dataIndex: 'pinned',
            render: function Render(pinned, { id }) {
                return (
                    <LemonButton
                        size="small"
                        onClick={
                            pinned
                                ? () => unpinDashboard(id, DashboardEventSource.DashboardsList)
                                : () => pinDashboard(id, DashboardEventSource.DashboardsList)
                        }
                        tooltip={pinned ? 'Unpin dashboard' : 'Pin dashboard'}
                        icon={pinned ? <IconPinFilled /> : <IconPin />}
                    />
                )
            },
        },
        {
            title: 'Name',
            dataIndex: 'name',
            width: '40%',
            render: function Render(_, { id, name, description, is_shared, user_access_level }) {
                const isPrimary = id === currentTeam?.primary_dashboard
                const canEditDashboard = accessLevelSatisfied(
                    AccessControlResourceType.Dashboard,
                    user_access_level,
                    AccessControlLevel.Editor
                )
                return (
                    <LemonTableLink
                        to={urls.dashboard(id)}
                        title={
                            <>
                                <span data-attr="dashboard-name">{name || 'Untitled'}</span>
                                {is_shared && (
                                    <Tooltip title="This dashboard is shared publicly.">
                                        <IconShare className="ml-1 text-base text-link" />
                                    </Tooltip>
                                )}
                                {!canEditDashboard && (
                                    <Tooltip title={DASHBOARD_CANNOT_EDIT_MESSAGE}>
                                        <IconLock className="ml-1 text-base text-secondary" />
                                    </Tooltip>
                                )}
                                {isPrimary && (
                                    <Tooltip title="The primary dashboard is shown on the project home page.">
                                        <span>
                                            <IconHome className="ml-1 text-base text-warning" />
                                        </span>
                                    </Tooltip>
                                )}
                            </>
                        }
                        description={description}
                    />
                )
            },
            sorter: nameCompareFunction,
        },
        {
            title: 'Tags',
            dataIndex: 'tags' as keyof DashboardType,
            render: function Render(tags: DashboardType['tags']) {
                return tags ? <ObjectTags tags={[...tags].sort()} staticOnly /> : null
            },
        } as LemonTableColumn<DashboardType, keyof DashboardType | undefined>,
        {
            title: 'Folder',
            dataIndex: 'folder' as keyof DashboardType,
            render: function Render(folder: DashboardType['folder']) {
                // Unfiled dashboards live in the default `Unfiled/Dashboards` folder — that's not a folder
                // the user chose, so show nothing rather than a filter affordance.
                if (folder === null || folder === undefined || folder === UNFILED_DASHBOARDS_FOLDER) {
                    return <span className="text-secondary">—</span>
                }
                const label = folder || 'Project root'
                return (
                    <Tooltip title={`Filter to dashboards in ${label}`}>
                        <Link className="flex items-center gap-1 text-secondary" onClick={() => setFilters({ folder })}>
                            <IconFolder className="shrink-0" />
                            <span className="truncate">{label}</span>
                        </Link>
                    </Tooltip>
                )
            },
        } as LemonTableColumn<DashboardType, keyof DashboardType | undefined>,
        createdByColumn<DashboardType>() as LemonTableColumn<DashboardType, keyof DashboardType | undefined>,
        createdAtColumn<DashboardType>() as LemonTableColumn<DashboardType, keyof DashboardType | undefined>,
        atColumn<DashboardType>('last_accessed_at', 'Last accessed at') as LemonTableColumn<
            DashboardType,
            keyof DashboardType | undefined
        >,
        hideActions
            ? {}
            : {
                  width: 0,
                  render: function RenderActions(_, dashboard: DashboardType) {
                      const { id, name, user_access_level } = dashboard
                      const moveEntry = fsEntryFor(id)
                      return (
                          <More
                              overlay={
                                  <>
                                      <LemonButton
                                          to={urls.dashboard(id)}
                                          onClick={() => {
                                              dashboardLogic({ id }).mount()
                                              dashboardLogic({ id }).actions.setDashboardMode(
                                                  null,
                                                  DashboardEventSource.DashboardsList
                                              )
                                          }}
                                          fullWidth
                                      >
                                          View
                                      </LemonButton>

                                      <AccessControlAction
                                          resourceType={AccessControlResourceType.Dashboard}
                                          minAccessLevel={AccessControlLevel.Editor}
                                          userAccessLevel={user_access_level}
                                      >
                                          <LemonButton
                                              to={urls.dashboard(id)}
                                              onClick={() => {
                                                  dashboardLogic({ id }).mount()
                                                  dashboardLogic({ id }).actions.setDashboardMode(
                                                      DashboardMode.Edit,
                                                      DashboardEventSource.DashboardsList
                                                  )
                                              }}
                                              fullWidth
                                          >
                                              Edit
                                          </LemonButton>
                                      </AccessControlAction>

                                      <LemonButton
                                          onClick={() => {
                                              showDuplicateDashboardModal(id, name)
                                          }}
                                          fullWidth
                                      >
                                          Duplicate
                                      </LemonButton>

                                      {moveEntry && (
                                          <AccessControlAction
                                              resourceType={AccessControlResourceType.Dashboard}
                                              minAccessLevel={AccessControlLevel.Editor}
                                              userAccessLevel={user_access_level}
                                          >
                                              <LemonButton
                                                  onClick={() => {
                                                      reportDashboardMoveInitiated('single', 1)
                                                      openMoveToModal([moveEntry as any])
                                                  }}
                                                  fullWidth
                                                  data-attr="dashboard-move-to-folder"
                                              >
                                                  Move to another folder
                                              </LemonButton>
                                          </AccessControlAction>
                                      )}

                                      <LemonDivider />

                                      <LemonRow
                                          icon={<IconHome className="size-4 text-warning" />}
                                          fullWidth
                                          status="warning"
                                      >
                                          <span className="text-secondary">
                                              Change the default dashboard
                                              <br />
                                              from the <Link to={urls.projectHomepage()}>project home page</Link>.
                                          </span>
                                      </LemonRow>

                                      <LemonDivider />

                                      <AccessControlAction
                                          resourceType={AccessControlResourceType.Dashboard}
                                          minAccessLevel={AccessControlLevel.Editor}
                                          userAccessLevel={user_access_level}
                                      >
                                          <LemonButton
                                              onClick={() => showDeleteDashboardModal(id)}
                                              fullWidth
                                              status="danger"
                                          >
                                              Delete dashboard
                                          </LemonButton>
                                      </AccessControlAction>
                                  </>
                              }
                          />
                      )
                  },
              },
    ]

    return (
        <>
            <DashboardsFiltersBar extraActions={extraActions} />
            <LemonTable
                data-attr="dashboards-table"
                pagination={{ pageSize: 100 }}
                dataSource={dashboards as DashboardType[]}
                rowKey="id"
                rowClassName={(record) => (record._highlight ? 'highlighted' : null)}
                columns={columns}
                loading={dashboardsLoading}
                defaultSorting={effectiveTableSorting}
                onSort={tableSortingChanged}
                emptyState="No dashboards matching your filters!"
                nouns={['dashboard', 'dashboards']}
                bulkSelection={{
                    barClassName: 'mb-2',
                    getKey: (dashboard: DashboardType): number => dashboard.id,
                    isRowSelectable: (dashboard: DashboardType) =>
                        accessLevelSatisfied(
                            AccessControlResourceType.Dashboard,
                            dashboard.user_access_level,
                            AccessControlLevel.Editor
                        )
                            ? true
                            : { disabledReason: DASHBOARD_CANNOT_EDIT_MESSAGE },
                    rowAriaLabel: (dashboard: DashboardType) => `Select dashboard ${dashboard.name}`,
                    headerAriaLabel: 'Select all dashboards on this page',
                    renderActions: (ctx) => {
                        // Move the whole selection at once, resolving each id's entry the same way the per-row
                        // Move does. Some rows may not resolve (e.g. unfiled dashboards the sidebar hasn't
                        // loaded) — surface that count rather than silently dropping them from the move.
                        // Tree arm only: in control the entry source is mostly empty, so the button would be
                        // perpetually disabled — leave control's bulk bar exactly as it was.
                        const moveEntries = isTreeArm
                            ? ctx.selectedKeys.map(fsEntryFor).filter((entry): entry is FileSystemEntry => !!entry)
                            : []
                        const unmovable = ctx.selectedKeys.length - moveEntries.length
                        const partial = unmovable > 0 && moveEntries.length > 0
                        return (
                            <>
                                {isTreeArm && (
                                    <LemonButton
                                        size="small"
                                        type="secondary"
                                        onClick={() => {
                                            reportDashboardMoveInitiated('bulk', moveEntries.length)
                                            openMoveToModal(moveEntries)
                                            ctx.clearSelection()
                                        }}
                                        disabledReason={
                                            moveEntries.length === 0
                                                ? 'None of the selected dashboards can be moved to a folder'
                                                : undefined
                                        }
                                        tooltip={
                                            partial
                                                ? `Only ${moveEntries.length} of ${ctx.selectedKeys.length} selected can be moved to a folder`
                                                : undefined
                                        }
                                        data-attr="dashboards-bulk-move-to-folder"
                                    >
                                        {partial ? `Move ${moveEntries.length} to folder` : 'Move to folder'}
                                    </LemonButton>
                                )}
                                <BulkUpdateTagsButton
                                    resource="dashboards"
                                    selectedIds={ctx.selectedKeys}
                                    onSuccess={() => {
                                        ctx.clearSelection()
                                        dashboardsModel.actions.loadDashboards()
                                    }}
                                />
                            </>
                        )
                    },
                }}
            />
        </>
    )
}
