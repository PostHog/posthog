import { dashboardTemplatesLogic } from 'scenes/dashboard/dashboards/templates/dashboardTemplatesLogic'
import { useActions, useValues } from 'kea'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { DashboardTemplatesRepositoryEntry } from 'scenes/dashboard/dashboards/templates/types'
import { dashboardsLogic } from 'scenes/dashboard/dashboards/dashboardsLogic'
import { LemonSnack } from 'lib/components/LemonSnack/LemonSnack'
import { LemonButton } from 'lib/components/LemonButton'
import { CommunityTag } from 'lib/CommunityTag'
import { IconCloudDownload } from 'lib/components/icons'

export const DashboardTemplatesTable = (): JSX.Element => {
    const { searchTerm } = useValues(dashboardsLogic)
    const { repository, repositoryLoading, templateLoading } = useValues(dashboardTemplatesLogic)
    const { installTemplate } = useActions(dashboardTemplatesLogic)

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
                            return (
                                <div className="template-installed">
                                    {installed ? (
                                        <LemonSnack>INSTALLED</LemonSnack>
                                    ) : (
                                        <LemonButton
                                            status={'primary'}
                                            type={'primary'}
                                            onClick={() => installTemplate({ name: record.name, url: record.url })}
                                            icon={<IconCloudDownload />}
                                            loading={templateLoading}
                                            disabled={templateLoading}
                                        >
                                            Install
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
