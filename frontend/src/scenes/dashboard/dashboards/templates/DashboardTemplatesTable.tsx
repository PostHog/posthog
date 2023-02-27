import { dashboardTemplatesLogic } from 'scenes/dashboard/dashboards/templates/dashboardTemplatesLogic'
import { useActions, useValues } from 'kea'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { dashboardsLogic } from 'scenes/dashboard/dashboards/dashboardsLogic'
import { LemonSnack } from 'lib/lemon-ui/LemonSnack/LemonSnack'
import { DashboardTemplateType } from '~/types'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { dashboardTemplateEditorLogic } from 'scenes/dashboard/dashboardTemplateEditorLogic'
import { DashboardTemplateEditor } from 'scenes/dashboard/DashboardTemplateEditor'
import { userLogic } from 'scenes/userLogic'
import { DashboardTemplatesRepositoryEntry } from 'scenes/dashboard/dashboards/templates/types'
import { CommunityTag } from 'lib/CommunityTag'
import { IconCloudUpload } from 'lib/lemon-ui/icons'

const ExternalDashboardTemplatesTable = (): JSX.Element => {
    const { searchTerm } = useValues(dashboardsLogic)
    const { repository, repositoryLoading, templateLoading, templateBeingSaved } = useValues(dashboardTemplatesLogic)
    const { installTemplate } = useActions(dashboardTemplatesLogic)
    const { user } = useValues(userLogic)

    return (
        <LemonTable
            data-attr="dashboards-template-table"
            pagination={{ pageSize: 10 }}
            dataSource={Object.values(repository)}
            rowKey="name"
            columns={
                [
                    {
                        title: 'Name',
                        dataIndex: 'name',
                        width: '80%',
                        render: function Render(name: string | undefined, record: DashboardTemplatesRepositoryEntry) {
                            return (
                                <div className="template-name flex flex-col gap-2">
                                    <div className="flex flex-row align-center gap-2">
                                        <span>{name}</span>
                                        <CommunityTag
                                            noun={'template'}
                                            isCommunity={record.maintainer !== 'official'}
                                        />
                                    </div>
                                    {record.description}
                                </div>
                            )
                        },
                        sorter: (a, b) => (a.name ?? 'Untitled').localeCompare(b.name ?? 'Untitled'),
                    },
                    {
                        title: 'Install',
                        dataIndex: 'installed',
                        width: '0',
                        render: function Render(
                            installed: boolean | undefined,
                            record: DashboardTemplatesRepositoryEntry
                        ) {
                            const recordUrl = record.url
                            return (
                                <div className="template-installed">
                                    {recordUrl === undefined || (installed && !record.has_new_version) ? (
                                        <LemonSnack>INSTALLED</LemonSnack>
                                    ) : (
                                        <LemonButton
                                            status={'primary'}
                                            type={'primary'}
                                            icon={<IconCloudUpload />}
                                            onClick={() => installTemplate({ name: record.name, url: recordUrl })}
                                            loading={templateLoading && templateBeingSaved === record.name}
                                            disabledReason={
                                                templateLoading
                                                    ? 'Installing template...'
                                                    : !user?.is_staff
                                                    ? 'Only staff users can install templates'
                                                    : undefined
                                            }
                                        >
                                            {record.has_new_version ? 'Update' : 'Install'}
                                        </LemonButton>
                                    )}
                                </div>
                            )
                        },
                        sorter: (a, b) => (a.name ?? 'Untitled').localeCompare(b.name ?? 'Untitled'),
                    },
                ] as LemonTableColumns<DashboardTemplatesRepositoryEntry>
            }
            loading={repositoryLoading}
            defaultSorting={{
                columnKey: 'name',
                order: 1,
            }}
            emptyState={
                searchTerm ? `No dashboard templates matching "${searchTerm}"!` : <>There are no dashboard templates.</>
            }
            nouns={['template', 'templates']}
        />
    )
}

export const DashboardTemplatesTable = (): JSX.Element | null => {
    const { searchTerm } = useValues(dashboardsLogic)
    const { allTemplates, repositoryLoading, isUsingDashboardTemplates, isUsingDashboardTemplatesV2 } =
        useValues(dashboardTemplatesLogic)

    const { openDashboardTemplateEditor, setDashboardTemplateId, deleteDashboardTemplate } =
        useActions(dashboardTemplateEditorLogic)

    if (isUsingDashboardTemplates && !isUsingDashboardTemplatesV2) {
        return <ExternalDashboardTemplatesTable />
    }

    if (!isUsingDashboardTemplatesV2) {
        return null
    }

    const columns: LemonTableColumns<DashboardTemplateType> = [
        {
            title: 'Name',
            dataIndex: 'template_name',
            render: (_, { template_name }) => {
                return <>{template_name}</>
            },
        },
        {
            title: 'Description',
            dataIndex: 'dashboard_description',
            render: (_, { dashboard_description }) => {
                return <>{dashboard_description}</>
            },
        },
        {
            title: 'Source',
            dataIndex: 'team_id',
            render: (_, { team_id }) => {
                if (team_id === null) {
                    return <LemonSnack>Official</LemonSnack>
                } else {
                    return <LemonSnack>Team</LemonSnack>
                }
            },
        },
        {
            width: 0,
            render: (_, { id }: DashboardTemplateType) => {
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton
                                    status="stealth"
                                    onClick={() => {
                                        if (id === undefined) {
                                            console.error('Dashboard template id not defined')
                                            return
                                        }
                                        setDashboardTemplateId(id)
                                        openDashboardTemplateEditor()
                                    }}
                                    fullWidth
                                >
                                    Edit
                                </LemonButton>

                                <LemonDivider />
                                <LemonButton
                                    onClick={() => {
                                        if (id === undefined) {
                                            console.error('Dashboard template id not defined')
                                            return
                                        }
                                        deleteDashboardTemplate(id)
                                    }}
                                    fullWidth
                                    status="danger"
                                >
                                    Delete dashboard
                                </LemonButton>
                            </>
                        }
                    />
                )
            },
        },
    ]

    return (
        <>
            <LemonTable
                data-attr="dashboards-template-table"
                pagination={{ pageSize: 10 }}
                dataSource={Object.values(allTemplates)}
                columns={columns}
                loading={repositoryLoading}
                defaultSorting={{
                    columnKey: 'name',
                    order: 1,
                }}
                emptyState={
                    searchTerm ? (
                        `No dashboard templates matching "${searchTerm}"!`
                    ) : (
                        <>There are no dashboard templates.</>
                    )
                }
                nouns={['template', 'templates']}
            />
            <DashboardTemplateEditor />
        </>
    )
}
