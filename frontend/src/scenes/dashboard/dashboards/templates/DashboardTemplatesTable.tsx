import { dashboardTemplatesLogic } from 'scenes/dashboard/dashboards/templates/dashboardTemplatesLogic'
import { useActions, useValues } from 'kea'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { dashboardsLogic } from 'scenes/dashboard/dashboards/dashboardsLogic'
import { LemonSnack } from 'lib/lemon-ui/LemonSnack/LemonSnack'
import { DashboardTemplateType } from '~/types'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { dashboardTemplateEditorLogic } from 'scenes/dashboard/DashboardTemplateEditorLogic'
import { DashboardTemplateEditor } from 'scenes/dashboard/DashboardTemplateEditor'

export const DashboardTemplatesTable = (): JSX.Element => {
    const { searchTerm } = useValues(dashboardsLogic)
    const { allTemplates, repositoryLoading } = useValues(dashboardTemplatesLogic)

    const { setOpenNewDashboardTemplateModal, setDashboardTemplateId, getDashboardTemplate, deleteDashboardTemplate } =
        useActions(dashboardTemplateEditorLogic)

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
                                        getDashboardTemplate(id)
                                        setOpenNewDashboardTemplateModal(true)
                                        console.log('open the modal')
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
