import { useActions, useValues } from 'kea'

import { LemonButton, LemonDialog, LemonInput, LemonTable, Spinner } from '@posthog/lemon-ui'

import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { urls } from 'scenes/urls'

import { sourceSummariesLogic } from '../logics/sourceSummariesLogic'
import { SourceIcon } from './SourceIcon'

export function DirectConnectSourcesTable(): JSX.Element {
    const { filteredDirectSourceSummaries, directSearchTerm, sourceReloadingById, sourceSummariesLoading } =
        useValues(sourceSummariesLogic)
    const { setDirectSearchTerm, reloadSource, deleteSource } = useActions(sourceSummariesLogic)

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
                dataSource={filteredDirectSourceSummaries}
                loading={sourceSummariesLoading}
                pagination={{ pageSize: 10 }}
                scrollToTopOnPageChange={false}
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
