import { useActions, useValues } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { Card, Tabs } from 'antd'
import { dashboardsLogic, DashboardsTab } from 'scenes/dashboard/dashboardsLogic'
import { Link } from 'lib/components/Link'
import { AppstoreAddOutlined, PushpinFilled, PushpinOutlined, ShareAltOutlined } from '@ant-design/icons'
import { NewDashboardModal } from 'scenes/dashboard/NewDashboardModal'
import { PageHeader } from 'lib/components/PageHeader'
import { AvailableFeature, DashboardMode, DashboardTemplateListing, DashboardType } from '~/types'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { userLogic } from 'scenes/userLogic'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { urls } from 'scenes/urls'
import { SceneExport } from 'scenes/sceneTypes'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/components/LemonTable'
import { createdAtColumn, createdByColumn } from 'lib/components/LemonTable/columnUtils'
import { LemonButton } from 'lib/components/LemonButton'
import { More } from 'lib/components/LemonButton/More'
import { dashboardLogic } from './dashboardLogic'
import { LemonRow } from 'lib/components/LemonRow'
import { LemonDivider } from 'lib/components/LemonDivider'
import { Tooltip } from 'lib/components/Tooltip'
import { IconCottage, IconLock } from 'lib/components/icons'
import { teamLogic } from 'scenes/teamLogic'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { DashboardPrivilegeLevel, FEATURE_FLAGS } from 'lib/constants'
import { inAppPromptLogic } from 'lib/logic/inAppPrompt/inAppPromptLogic'
import { LemonInput } from '@posthog/lemon-ui'
import { deleteDashboardLogic } from 'scenes/dashboard/deleteDashboardLogic'
import { DeleteDashboardModal } from 'scenes/dashboard/DeleteDashboardModal'
import { DuplicateDashboardModal } from 'scenes/dashboard/DuplicateDashboardModal'
import { duplicateDashboardLogic } from 'scenes/dashboard/duplicateDashboardLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { dashboardTemplateLogic } from 'scenes/dashboard/dashboardTemplates/dashboardTemplateLogic'

export const scene: SceneExport = {
    component: Dashboards,
    logic: dashboardsLogic,
}

export function Dashboards(): JSX.Element {
    const { dashboardsLoading } = useValues(dashboardsModel)
    const { unpinDashboard, pinDashboard } = useActions(dashboardsModel)
    const { setSearchTerm, setCurrentTab } = useActions(dashboardsLogic)
    const { dashboards, searchTerm, currentTab } = useValues(dashboardsLogic)
    const { showNewDashboardModal, addDashboard, setNewDashboardValue } = useActions(newDashboardLogic)
    const { hasAvailableFeature } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const { closePrompts } = useActions(inAppPromptLogic)
    const { showDuplicateDashboardModal } = useActions(duplicateDashboardLogic)
    const { showDeleteDashboardModal } = useActions(deleteDashboardLogic)
    const { renameDashboardTemplate } = useActions(dashboardTemplateLogic)

    const { featureFlags } = useValues(featureFlagLogic)

    const columns: LemonTableColumns<DashboardType> =
        currentTab === DashboardsTab.Templates
            ? []
            : ([
                  {
                      width: 0,
                      dataIndex: 'pinned',
                      render: function Render(pinned, { id }) {
                          return (
                              <LemonButton
                                  size="small"
                                  status="primary-alt"
                                  onClick={
                                      pinned
                                          ? () => unpinDashboard(id, DashboardEventSource.DashboardsList)
                                          : () => pinDashboard(id, DashboardEventSource.DashboardsList)
                                  }
                              >
                                  {pinned ? <PushpinFilled /> : <PushpinOutlined />}
                              </LemonButton>
                          )
                      },
                  },
                  {
                      title: 'Name',
                      dataIndex: 'name',
                      width: '40%',
                      render: function Render(
                          name,
                          { id, description, _highlight, is_shared, effective_privilege_level }
                      ) {
                          const isPrimary = id === currentTeam?.primary_dashboard
                          const canEditDashboard = effective_privilege_level >= DashboardPrivilegeLevel.CanEdit
                          return (
                              <div
                                  className={_highlight ? 'highlighted' : undefined}
                                  style={{ display: 'inline-block' }}
                              >
                                  <div className="row-name">
                                      <Link data-attr="dashboard-name" to={urls.dashboard(id)}>
                                          {name || 'Untitled'}
                                      </Link>
                                      {!canEditDashboard && (
                                          <Tooltip title="You don't have edit permissions for this dashboard.">
                                              <IconLock
                                                  style={{
                                                      marginLeft: 6,
                                                      verticalAlign: '-0.125em',
                                                      display: 'inline',
                                                  }}
                                              />
                                          </Tooltip>
                                      )}
                                      {is_shared && (
                                          <Tooltip title="This dashboard is shared publicly.">
                                              <ShareAltOutlined style={{ marginLeft: 6 }} />
                                          </Tooltip>
                                      )}
                                      {isPrimary && (
                                          <Tooltip title="Primary dashboards are shown on the project home page">
                                              <IconCottage
                                                  style={{
                                                      marginLeft: 6,
                                                      color: 'var(--warning)',
                                                      fontSize: '1rem',
                                                      verticalAlign: '-0.125em',
                                                      display: 'inline',
                                                  }}
                                              />
                                          </Tooltip>
                                      )}
                                  </div>
                                  {hasAvailableFeature(AvailableFeature.DASHBOARD_COLLABORATION) && description && (
                                      <span className="row-description">{description}</span>
                                  )}
                              </div>
                          )
                      },
                      sorter: (a, b) => (a.name ?? 'Untitled').localeCompare(b.name ?? 'Untitled'),
                  },
                  ...(hasAvailableFeature(AvailableFeature.TAGGING)
                      ? [
                            {
                                title: 'Tags',
                                dataIndex: 'tags' as keyof DashboardType,
                                render: function Render(tags: DashboardType['tags']) {
                                    return tags ? <ObjectTags tags={tags} staticOnly /> : null
                                },
                            } as LemonTableColumn<DashboardType, keyof DashboardType | undefined>,
                        ]
                      : []),
                  createdByColumn<DashboardType>() as LemonTableColumn<DashboardType, keyof DashboardType | undefined>,
                  createdAtColumn<DashboardType>() as LemonTableColumn<DashboardType, keyof DashboardType | undefined>,
                  {
                      width: 0,
                      render: function RenderActions(_, { id, name }: DashboardType) {
                          return (
                              <More
                                  overlay={
                                      <div style={{ maxWidth: 250 }}>
                                          <LemonButton
                                              status="stealth"
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
                                          <LemonButton
                                              status="stealth"
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
                                          <LemonButton
                                              status="stealth"
                                              onClick={() => {
                                                  showDuplicateDashboardModal(id, name)
                                              }}
                                              fullWidth
                                          >
                                              Duplicate
                                          </LemonButton>
                                          <LemonDivider />
                                          <LemonRow
                                              icon={<IconCottage className="text-warning" />}
                                              fullWidth
                                              status="warning"
                                          >
                                              <span className="text-muted">
                                                  Change the default dashboard on the{' '}
                                                  <Link to={urls.projectHomepage()}>project home page</Link>.
                                              </span>
                                          </LemonRow>
                                          <LemonDivider />
                                          <LemonButton
                                              onClick={() => {
                                                  showDeleteDashboardModal(id)
                                              }}
                                              fullWidth
                                              status="danger"
                                          >
                                              Delete dashboard
                                          </LemonButton>
                                      </div>
                                  }
                              />
                          )
                      },
                  },
              ] as LemonTableColumns<DashboardType>)

    return (
        <div>
            <NewDashboardModal />
            <DuplicateDashboardModal />
            <DeleteDashboardModal />
            <PageHeader
                title="Dashboards"
                buttons={
                    <LemonButton
                        data-attr={'new-dashboard'}
                        onClick={() => {
                            closePrompts()
                            showNewDashboardModal()
                        }}
                        type="primary"
                    >
                        New dashboard
                    </LemonButton>
                }
            />
            <Tabs
                activeKey={currentTab}
                style={{ borderColor: '#D9D9D9' }}
                onChange={(tab) => setCurrentTab(tab as DashboardsTab)}
            >
                <Tabs.TabPane tab="All Dashboards" key={DashboardsTab.All} />
                <Tabs.TabPane tab="Your Dashboards" key={DashboardsTab.Yours} />
                <Tabs.TabPane tab="Pinned" key={DashboardsTab.Pinned} />
                <Tabs.TabPane tab="Shared" key={DashboardsTab.Shared} />
                {!!featureFlags[FEATURE_FLAGS.DASHBOARD_TEMPLATES] && (
                    <Tabs.TabPane tab="Templates" key={DashboardsTab.Templates} />
                )}
            </Tabs>
            <div className="flex">
                <LemonInput
                    type="search"
                    placeholder="Search for dashboards"
                    onChange={setSearchTerm}
                    value={searchTerm}
                />
                <div />
            </div>
            <LemonDivider className="my-4" />
            {currentTab === DashboardsTab.Templates ? (
                <LemonTable
                    data-attr="dashboards-template-table"
                    pagination={{ pageSize: 100 }}
                    dataSource={dashboards as DashboardTemplateListing[]}
                    rowKey="template_name"
                    columns={
                        [
                            {
                                title: 'Name',
                                dataIndex: 'template_name',
                                // width: '80%',
                                render: function Render(template_name: string | undefined) {
                                    return <div className="row-template-name">{template_name}</div>
                                },
                                sorter: (a, b) =>
                                    (a.template_name ?? 'Untitled').localeCompare(b.template_name ?? 'Untitled'),
                            },
                            {
                                width: 0,
                                render: function RenderActions(_, { id, template_name }: DashboardTemplateListing) {
                                    return (
                                        <More
                                            overlay={
                                                <div style={{ maxWidth: 250 }}>
                                                    <LemonButton
                                                        status="stealth"
                                                        onClick={() => {
                                                            setNewDashboardValue('useTemplate', id)
                                                            showNewDashboardModal()
                                                        }}
                                                        fullWidth
                                                    >
                                                        Create dashboard using this template
                                                    </LemonButton>
                                                    <LemonButton
                                                        status="stealth"
                                                        onClick={() => {
                                                            console.log('boo!')
                                                            renameDashboardTemplate(id, template_name)
                                                        }}
                                                        fullWidth
                                                    >
                                                        Rename template
                                                    </LemonButton>

                                                    <LemonDivider />

                                                    <LemonButton
                                                        onClick={() => {
                                                            console.log('delete')
                                                        }}
                                                        fullWidth
                                                        status="danger"
                                                    >
                                                        Delete dashboard template
                                                    </LemonButton>
                                                </div>
                                            }
                                        />
                                    )
                                },
                            },
                        ] as LemonTableColumns<DashboardTemplateListing>
                    }
                    loading={false}
                    defaultSorting={{
                        columnKey: 'name',
                        order: 1,
                    }}
                    emptyState={
                        searchTerm ? (
                            `No dashboard template matching "${searchTerm}"!`
                        ) : (
                            <>
                                There are no dashboard templates. Create them from dashboards and they will appear here.
                            </>
                        )
                    }
                    nouns={['template', 'templates']}
                />
            ) : dashboardsLoading || dashboards.length > 0 || searchTerm || currentTab !== DashboardsTab.All ? (
                <LemonTable
                    data-attr="dashboards-table"
                    pagination={{ pageSize: 100 }}
                    dataSource={dashboards as DashboardType[]}
                    rowKey="id"
                    columns={columns}
                    loading={dashboardsLoading}
                    defaultSorting={{ columnKey: 'name', order: 1 }}
                    emptyState={
                        searchTerm ? (
                            `No ${
                                currentTab === DashboardsTab.Pinned
                                    ? 'pinned '
                                    : currentTab === DashboardsTab.Shared
                                    ? 'shared '
                                    : ''
                            }dashboards matching "${searchTerm}"!`
                        ) : currentTab === DashboardsTab.Pinned ? (
                            <>
                                No dashboards have been pinned for quick access yet.{' '}
                                <Link onClick={() => setCurrentTab(DashboardsTab.All)}>
                                    Go to All Dashboards to pin one.
                                </Link>
                            </>
                        ) : currentTab === DashboardsTab.Shared ? (
                            <>
                                No dashboards have been shared yet.{' '}
                                <Link onClick={() => setCurrentTab(DashboardsTab.All)}>
                                    Go to All Dashboards to share one.
                                </Link>
                            </>
                        ) : undefined
                    }
                    nouns={['dashboard', 'dashboards']}
                />
            ) : (
                <div className="mt-4">
                    <p>Create your first dashboard:</p>
                    <div className="flex justify-center items-center gap-4">
                        <Card
                            title="Empty"
                            size="small"
                            style={{ width: 200, cursor: 'pointer' }}
                            onClick={() =>
                                addDashboard({
                                    name: 'New Dashboard',
                                    useTemplate: '',
                                })
                            }
                        >
                            <div style={{ textAlign: 'center', fontSize: 40 }}>
                                <AppstoreAddOutlined />
                            </div>
                        </Card>
                        <Card
                            title="App Default"
                            size="small"
                            style={{ width: 200, cursor: 'pointer' }}
                            onClick={() =>
                                addDashboard({
                                    name: 'Web App Dashboard',
                                    useTemplate: 'DEFAULT_APP',
                                })
                            }
                        >
                            <div style={{ textAlign: 'center', fontSize: 40 }}>
                                <AppstoreAddOutlined />
                            </div>
                        </Card>
                    </div>
                </div>
            )}
        </div>
    )
}
