import { dashboardTemplatesLogic } from 'scenes/dashboard/dashboards/templates/dashboardTemplatesLogic'
import { useValues } from 'kea'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { DashboardTemplatesRepositoryEntry } from 'scenes/dashboard/dashboards/templates/types'
import { dashboardsLogic } from 'scenes/dashboard/dashboards/dashboardsLogic'
import { CommunityTag } from 'lib/CommunityTag'
import { IconGithub } from 'lib/lemon-ui/icons'
import { Link } from '@posthog/lemon-ui'

export const DashboardTemplatesTable = (): JSX.Element => {
    const { searchTerm } = useValues(dashboardsLogic)
    const { repository, repositoryLoading } = useValues(dashboardTemplatesLogic)

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
                        title: 'URL',
                        dataIndex: 'url',
                        width: '0',
                        render: function Render(url: string) {
                            return (
                                <div className="template-installed">
                                    <Link to={url} disableClientSideRouting target="blank">
                                        View in GitHub <IconGithub />
                                    </Link>
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
