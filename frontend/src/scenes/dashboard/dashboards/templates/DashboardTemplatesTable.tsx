import { dashboardTemplatesLogic } from 'scenes/dashboard/dashboards/templates/dashboardTemplatesLogic'
import { useValues } from 'kea'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { dashboardsLogic } from 'scenes/dashboard/dashboards/dashboardsLogic'
import { LemonSnack } from 'lib/lemon-ui/LemonSnack/LemonSnack'

export const DashboardTemplatesTable = (): JSX.Element => {
    const { searchTerm } = useValues(dashboardsLogic)
    const { allTemplates, repositoryLoading } = useValues(dashboardTemplatesLogic)

    return (
        <LemonTable
            data-attr="dashboards-template-table"
            pagination={{ pageSize: 10 }}
            dataSource={Object.values(allTemplates)}
            columns={[
                {
                    title: 'Name',
                    dataIndex: 'template_name',
                    render: (name: string) => <>{name}</>,
                },
                {
                    title: 'Description',
                    dataIndex: 'dashboard_description',
                    render: (description: string) => <>{description}</>,
                },
                {
                    title: 'Source',
                    dataIndex: 'team_id',
                    render: (teamId: number) => {
                        if (teamId === null) {
                            return <LemonSnack>Official</LemonSnack>
                        } else {
                            return <LemonSnack>Team</LemonSnack>
                        }
                    },
                },
            ]}
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
