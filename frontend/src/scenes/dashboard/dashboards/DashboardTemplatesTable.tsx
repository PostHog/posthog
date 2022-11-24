import { useActions, useValues } from 'kea'
import { dashboardsLogic } from 'scenes/dashboard/dashboards/dashboardsLogic'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { dashboardTemplateLogic } from 'scenes/dashboard/dashboardTemplates/dashboardTemplateLogic'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { DashboardTemplateListing, DashboardTemplateScope, ExporterFormat } from '~/types'
import { More } from 'lib/components/LemonButton/More'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonDivider } from 'lib/components/LemonDivider'
import { Tooltip } from 'lib/components/Tooltip'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'
import { teamLogic } from 'scenes/teamLogic'
import { OrganizationMembershipLevel } from 'lib/constants'
import { ExportButton } from 'lib/components/ExportButton/ExportButton'
import { slugify } from 'lib/utils'
import api from 'lib/api'

export const DashboardTemplatesTable = (): JSX.Element => {
    const { filteredDashboardTemplates, searchTerm } = useValues(dashboardsLogic)
    const { showNewDashboardModal, setNewDashboardValue } = useActions(newDashboardLogic)
    const { renameDashboardTemplate, deleteDashboardTemplate } = useActions(dashboardTemplateLogic)
    const { dashboardTemplatesLoading } = useValues(dashboardTemplateLogic)
    const { currentTeam } = useValues(teamLogic)

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
                        width: '80%',
                        render: function Render(template_name: string | undefined) {
                            return <div className="row-template-name">{template_name}</div>
                        },
                        sorter: (a, b) => (a.template_name ?? 'Untitled').localeCompare(b.template_name ?? 'Untitled'),
                    },
                    {
                        title: 'Scope',
                        dataIndex: 'scope',
                        width: '20%',
                        render: function Render(scope: DashboardTemplateScope | undefined) {
                            const tooltip =
                                scope === 'project'
                                    ? `This template is only visible in the current project`
                                    : scope === 'organization'
                                    ? `This template is visible to all users in the current organization`
                                    : `This template is visible to all users`
                            return (
                                <Tooltip title={tooltip} placement="right">
                                    <LemonTag className="uppercase">{scope}</LemonTag>
                                </Tooltip>
                            )
                        },
                        sorter: (a, b) => a.scope.localeCompare(b.scope),
                    },
                    {
                        width: 0,
                        render: function RenderActions(_, { id, template_name, scope }: DashboardTemplateListing) {
                            const canEverEdit = scope !== 'global'
                            const disabled =
                                scope === 'organization' &&
                                currentTeam?.effective_membership_level === OrganizationMembershipLevel.Member
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
                                                New dashboard from this template
                                            </LemonButton>

                                            <ExportButton
                                                fullWidth
                                                items={[
                                                    {
                                                        export_format: ExporterFormat.JSON,
                                                        export_context: {
                                                            path: api.dashboardTemplates.exportURL(id),
                                                            filename: `export-${slugify(template_name)}`,
                                                        },
                                                    },
                                                ]}
                                            />
                                            {canEverEdit && (
                                                <>
                                                    <LemonButton
                                                        status="stealth"
                                                        onClick={() => {
                                                            renameDashboardTemplate(id, template_name)
                                                        }}
                                                        disabled={disabled}
                                                        fullWidth
                                                    >
                                                        Rename template
                                                    </LemonButton>

                                                    <LemonDivider />

                                                    <LemonButton
                                                        onClick={() => {
                                                            deleteDashboardTemplate(id)
                                                        }}
                                                        disabled={disabled}
                                                        fullWidth
                                                        status="danger"
                                                    >
                                                        Delete dashboard template
                                                    </LemonButton>
                                                </>
                                            )}
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
