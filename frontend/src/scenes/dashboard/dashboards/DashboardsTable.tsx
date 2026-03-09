import { useActions, useValues } from 'kea'

import { IconHome, IconLock, IconPin, IconPinFilled, IconShare } from '@posthog/icons'

import { AccessControlAction } from 'lib/components/AccessControlAction'
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
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { dashboardsLogic } from 'scenes/dashboard/dashboards/dashboardsLogic'
import { deleteDashboardLogic } from 'scenes/dashboard/deleteDashboardLogic'
import { duplicateDashboardLogic } from 'scenes/dashboard/duplicateDashboardLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { splitPath } from '~/layout/panel-layout/ProjectTree/utils'
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

export function getDashboardFolderLabelFromItems(
    itemsByRef: Record<string, { path?: string }>,
    id: DashboardType['id']
): string {
    const entry = itemsByRef[`dashboard::${id}`]
    const folderParts = splitPath(entry?.path).slice(0, -1)
    if (folderParts.length === 0) {
        return '—'
    }
    return folderParts.join(' / ')
}

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
    const { itemsByRef } = useValues(projectTreeDataLogic)

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
            key: 'folder',
            render: function RenderFolder(_, { id }: DashboardType) {
                return getDashboardFolderLabelFromItems(itemsByRef, id)
            },
        },
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

                                      <LemonDivider />

                                      <LemonRow icon={<IconHome className="text-warning" />} fullWidth status="warning">
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
                defaultSorting={tableSorting}
                onSort={tableSortingChanged}
                emptyState="No dashboards matching your filters!"
                nouns={['dashboard', 'dashboards']}
            />
        </>
    )
}
