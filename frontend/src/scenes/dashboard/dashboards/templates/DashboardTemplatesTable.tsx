import { useActions, useValues } from 'kea'

import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonSnack } from 'lib/lemon-ui/LemonSnack/LemonSnack'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { DashboardTemplateEditor } from 'scenes/dashboard/DashboardTemplateEditor'
import { dashboardTemplateEditorLogic } from 'scenes/dashboard/dashboardTemplateEditorLogic'
import { dashboardTemplatesLogic } from 'scenes/dashboard/dashboards/templates/dashboardTemplatesLogic'
import { userLogic } from 'scenes/userLogic'

import { DashboardTemplateType } from '~/types'

export const DashboardTemplatesTable = (): JSX.Element | null => {
    const { allTemplates, allTemplatesLoading } = useValues(dashboardTemplatesLogic)

    const { openDashboardTemplateEditor, setDashboardTemplateId, deleteDashboardTemplate, updateDashboardTemplate } =
        useActions(dashboardTemplateEditorLogic)

    const { user } = useValues(userLogic)

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
            title: 'Type',
            dataIndex: 'team_id',
            render: (_, { scope }) => {
                if (scope === 'global') {
                    return <LemonSnack>Official</LemonSnack>
                }
                return <LemonSnack>Team</LemonSnack>
            },
        },
        {
            width: 0,
            render: (_, { id, scope }: DashboardTemplateType) => {
                if (!user?.is_staff) {
                    return null
                }
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton
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
                                <LemonButton
                                    onClick={() => {
                                        if (id === undefined) {
                                            console.error('Dashboard template id not defined')
                                            return
                                        }
                                        updateDashboardTemplate({
                                            id,
                                            dashboardTemplateUpdates: {
                                                scope: scope === 'global' ? 'team' : 'global',
                                            },
                                        })
                                    }}
                                    fullWidth
                                >
                                    Make visible to {scope === 'global' ? 'this team only' : 'everyone'}
                                </LemonButton>

                                <LemonDivider />
                                <LemonButton
                                    onClick={() => {
                                        if (id === undefined) {
                                            console.error('Dashboard template id not defined')
                                            return
                                        }
                                        LemonDialog.open({
                                            title: 'Delete dashboard template?',
                                            description: 'This action cannot be undone.',
                                            primaryButton: {
                                                status: 'danger',
                                                children: 'Delete',
                                                onClick: () => {
                                                    deleteDashboardTemplate(id)
                                                },
                                            },
                                        })
                                    }}
                                    fullWidth
                                    status="danger"
                                    disabledReason={
                                        scope === 'global'
                                            ? 'Cannot delete global dashboard templates, make them team only first'
                                            : undefined
                                    }
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
                loading={allTemplatesLoading}
                defaultSorting={{
                    columnKey: 'name',
                    order: 1,
                }}
                emptyState={<>There are no dashboard templates.</>}
                nouns={['template', 'templates']}
            />
            <DashboardTemplateEditor />
        </>
    )
}
