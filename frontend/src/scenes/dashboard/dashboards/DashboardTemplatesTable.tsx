import { useActions, useValues } from 'kea'
import { dashboardsLogic } from 'scenes/dashboard/dashboards/dashboardsLogic'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { dashboardTemplateLogic } from 'scenes/dashboard/dashboardTemplates/dashboardTemplateLogic'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { DashboardTemplateListing } from '~/types'
import { More } from 'lib/components/LemonButton/More'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonDivider } from 'lib/components/LemonDivider'

export const DashboardTemplatesTable = (): JSX.Element => {
    const { filteredDashboardTemplates, searchTerm } = useValues(dashboardsLogic)
    const { showNewDashboardModal, setNewDashboardValue } = useActions(newDashboardLogic)
    const { renameDashboardTemplate, deleteDashboardTemplate } = useActions(dashboardTemplateLogic)
    const { dashboardTemplatesLoading } = useValues(dashboardTemplateLogic)

    return (
        <LemonTable
            data-attr="dashboards-template-table"
            pagination={{ pageSize: 100 }}
            dataSource={filteredDashboardTemplates}
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
                        sorter: (a, b) => (a.template_name ?? 'Untitled').localeCompare(b.template_name ?? 'Untitled'),
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
                                                    deleteDashboardTemplate(id)
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
            loading={dashboardTemplatesLoading}
            defaultSorting={{
                columnKey: 'name',
                order: 1,
            }}
            emptyState={
                searchTerm ? (
                    `No dashboard template matching "${searchTerm}"!`
                ) : (
                    <>There are no dashboard templates. Create them from dashboards and they will appear here.</>
                )
            }
            nouns={['template', 'templates']}
        />
    )
}
