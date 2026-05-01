import { useActions, useValues } from 'kea'

import { IconHome, IconLock, IconPin, IconPinFilled, IconShare } from '@posthog/icons'
import { LemonCheckbox } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { BulkActionToolbar } from 'lib/components/BulkActions/BulkActionToolbar'
import { SelectionCheckbox } from 'lib/components/BulkActions/SelectionCheckbox'
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
import { getSelectionState, listSelectionLogic } from 'lib/logic/listSelectionLogic'
import { accessLevelSatisfied } from 'lib/utils/accessControlUtils'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { dashboardsLogic } from 'scenes/dashboard/dashboards/dashboardsLogic'
import { deleteDashboardLogic } from 'scenes/dashboard/deleteDashboardLogic'
import { duplicateDashboardLogic } from 'scenes/dashboard/duplicateDashboardLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { dashboardsModel, nameCompareFunction } from '~/models/dashboardsModel'
import {
    AccessControlLevel,
    AccessControlResourceType,
    DashboardBasicType,
    DashboardMode,
    DashboardType,
} from '~/types'

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
}

export function DashboardsTable({
    dashboards,
    dashboardsLoading,
    extraActions,
    hideActions,
}: DashboardsTableProps): JSX.Element {
    const { unpinDashboard, pinDashboard } = useActions(dashboardsModel)
    const { tableSortingChanged } = useActions(dashboardsLogic)
    const { tableSorting } = useValues(dashboardsLogic)
    const { currentTeam } = useValues(teamLogic)
    const { showDuplicateDashboardModal } = useActions(duplicateDashboardLogic)
    const { showDeleteDashboardModal } = useActions(deleteDashboardLogic)
    const { openMoveToModal } = useActions(moveToLogic)
    const { itemsByRef } = useValues(projectTreeDataLogic)

    const dashboardSelection = listSelectionLogic({ resource: 'dashboards' })
    const { selectedIds } = useValues(dashboardSelection)
    const { selectAllOnPage } = useActions(dashboardSelection)

    const allPageItems = (dashboards as DashboardType[]).map((d) => ({
        id: d.id,
        isEditable: accessLevelSatisfied(
            AccessControlResourceType.Dashboard,
            d.user_access_level,
            AccessControlLevel.Editor
        ),
    }))
    const editableIds = allPageItems.filter((item) => item.isEditable).map((item) => item.id)

    const { isAllSelected, isSomeSelected } = getSelectionState(selectedIds, editableIds)

    const columns: LemonTableColumns<DashboardType> = [
        {
            key: 'selection',
            width: 32,
            title: (
                <LemonCheckbox
                    checked={isSomeSelected ? 'indeterminate' : isAllSelected}
                    onChange={() => selectAllOnPage(allPageItems)}
                    aria-label="Select all dashboards on this page"
                />
            ),
            render: function Render(_: unknown, dashboard: DashboardType, index: number) {
                const canEdit = accessLevelSatisfied(
                    AccessControlResourceType.Dashboard,
                    dashboard.user_access_level,
                    AccessControlLevel.Editor
                )
                return (
                    <SelectionCheckbox
                        resource="dashboards"
                        id={dashboard.id}
                        index={index}
                        allPageItems={allPageItems}
                        disabledReason={!canEdit ? DASHBOARD_CANNOT_EDIT_MESSAGE : undefined}
                        ariaLabel={`Select dashboard ${dashboard.name}`}
                    />
                )
            },
        },
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
                  render: function RenderActions(_, { id, name, user_access_level }: DashboardType) {
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

                                      {itemsByRef[`dashboard::${id}`] && (
                                          <AccessControlAction
                                              resourceType={AccessControlResourceType.Dashboard}
                                              minAccessLevel={AccessControlLevel.Editor}
                                              userAccessLevel={user_access_level}
                                          >
                                              <LemonButton
                                                  onClick={() => {
                                                      const entry = itemsByRef[`dashboard::${id}`]
                                                      openMoveToModal([entry as any])
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
            {selectedIds.length > 0 && (
                <div className="flex items-center justify-end gap-2 min-h-12">
                    <BulkActionToolbar resource="dashboards" />
                </div>
            )}
            <LemonTable
                data-attr="dashboards-table"
                pagination={{ pageSize: 100 }}
                dataSource={dashboards as DashboardType[]}
                rowKey="id"
                rowClassName={(record) => (record._highlight ? 'highlighted' : null)}
                columns={columns}
                loading={dashboardsLoading}
                defaultSorting={tableSorting}
                onSort={tableSortingChanged}
                emptyState="No dashboards matching your filters!"
                nouns={['dashboard', 'dashboards']}
            />
        </>
    )
}
