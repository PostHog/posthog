import { useActions, useValues } from 'kea'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInput, LemonTable, Spinner } from '@posthog/lemon-ui'

import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { urls } from 'scenes/urls'

import { sourceManagementLogic } from '../logics/sourceManagementLogic'
import { SourceIcon } from './SourceIcon'

export function DirectConnectSourcesTable(): JSX.Element {
    const { filteredDirectSources, directSearchTerm, sourceReloadingById, dataWarehouseSourcesLoading } =
        useValues(sourceManagementLogic)
    const { setDirectSearchTerm, reloadSource, deleteSource } = useActions(sourceManagementLogic)

    return (
        <div>
            <div className="flex gap-2 justify-between items-center mb-4">
                <LemonInput
                    type="search"
                    placeholder="Search..."
                    onChange={setDirectSearchTerm}
                    value={directSearchTerm}
                />
            </div>
            <LemonTable
                id="direct-connect-sources"
                dataSource={filteredDirectSources}
                loading={dataWarehouseSourcesLoading}
                pagination={{ pageSize: 10 }}
                scrollToTopOnPageChange={false}
                emptyState={
                    <div className="flex flex-col items-center gap-2 py-2">
                        <span>
                            {directSearchTerm ? 'No sources matching your search' : 'No direct connect sources'}
                        </span>
                        <LemonButton
                            type="secondary"
                            icon={<IconPlusSmall />}
                            to={urls.dataWarehouseSourceNew()}
                            size="small"
                            data-attr="direct-connect-sources-empty-new-source"
                        >
                            New source
                        </LemonButton>
                    </div>
                }
                columns={[
                    {
                        width: 0,
                        render: (_, source) => <SourceIcon type={source.source_type} />,
                    },
                    {
                        title: 'Source',
                        key: 'name',
                        render: (_, source) => (
                            <LemonTableLink
                                to={urls.dataWarehouseSource(`managed-${source.id}`)}
                                title={source.prefix || source.source_type}
                                description={source.description}
                            />
                        ),
                    },
                    {
                        key: 'actions',
                        render: (_, source) => (
                            <div className="flex flex-row justify-end">
                                {sourceReloadingById[source.id] ? (
                                    <Spinner />
                                ) : (
                                    <>
                                        <LemonButton
                                            data-attr={`reload-data-warehouse-${source.source_type}`}
                                            onClick={() => reloadSource(source)}
                                        >
                                            Reload
                                        </LemonButton>
                                        <LemonButton
                                            status="danger"
                                            data-attr={`delete-data-warehouse-${source.source_type}`}
                                            onClick={() => {
                                                LemonDialog.open({
                                                    title: 'Delete data source?',
                                                    description:
                                                        'Are you sure you want to delete this data source? All related tables will be deleted.',
                                                    primaryButton: {
                                                        children: 'Delete',
                                                        status: 'danger',
                                                        onClick: () => deleteSource(source),
                                                    },
                                                    secondaryButton: {
                                                        children: 'Cancel',
                                                    },
                                                })
                                            }}
                                        >
                                            Delete
                                        </LemonButton>
                                    </>
                                )}
                            </div>
                        ),
                    },
                ]}
            />
        </div>
    )
}
