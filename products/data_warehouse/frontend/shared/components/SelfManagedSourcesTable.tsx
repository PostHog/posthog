import { useActions, useValues } from 'kea'

import { LemonButton, LemonDialog, LemonInput, LemonTable, Spinner } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { DatabaseSchemaDataWarehouseTable } from '~/queries/schema/schema-general'
import { ExternalDataSource } from '~/types'

import { sourceManagementLogic } from '../logics/sourceManagementLogic'
import { sourcesDataLogic } from '../logics/sourcesDataLogic'
import { SourceIcon, mapUrlToProvider } from './SourceIcon'

export function SelfManagedSourcesTable(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { filteredSelfManagedTables, searchTerm, sourceReloadingById } = useValues(sourceManagementLogic)
    const { deleteSelfManagedTable, refreshSelfManagedTableSchema, setSearchTerm, reloadSource, deleteSource } =
        useActions(sourceManagementLogic)
    const { dataWarehouseSources, dataWarehouseSourcesLoading } = useValues(sourcesDataLogic)
    const isDirectQueryEnabled = !!featureFlags[FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY]

    const directSources = isDirectQueryEnabled
        ? (dataWarehouseSources?.results ?? [])
              .filter((source) => source.access_method?.toLowerCase() === 'direct')
              .filter((source) => {
                  if (!searchTerm?.trim()) {
                      return true
                  }
                  const normalizedSearch = searchTerm.toLowerCase()
                  return (
                      source.source_type.toLowerCase().includes(normalizedSearch) ||
                      source.prefix?.toLowerCase().includes(normalizedSearch) ||
                      source.description?.toLowerCase().includes(normalizedSearch)
                  )
              })
        : []

    const rows: Array<
        { kind: 'direct'; source: ExternalDataSource } | { kind: 'table'; table: DatabaseSchemaDataWarehouseTable }
    > = [
        ...directSources.map((source) => ({ kind: 'direct' as const, source })),
        ...filteredSelfManagedTables.map((table) => ({ kind: 'table' as const, table })),
    ]

    return (
        <div>
            <div className="flex gap-2 justify-between items-center mb-4">
                <LemonInput type="search" placeholder="Search..." onChange={setSearchTerm} value={searchTerm} />
            </div>
            <LemonTable
                id="self-managed-sources"
                dataSource={rows}
                loading={isDirectQueryEnabled ? dataWarehouseSourcesLoading : undefined}
                pagination={{ pageSize: 10 }}
                columns={[
                    {
                        width: 0,
                        render: (_, row) =>
                            row.kind === 'direct' ? (
                                <SourceIcon type={row.source.source_type} />
                            ) : (
                                <SourceIcon type={mapUrlToProvider(row.table.url_pattern)} />
                            ),
                    },
                    {
                        title: 'Source',
                        key: 'name',
                        render: (_, row) =>
                            row.kind === 'direct' ? (
                                <LemonTableLink
                                    to={urls.dataWarehouseSource(`managed-${row.source.id}`)}
                                    title={row.source.prefix || row.source.source_type}
                                    description={row.source.description}
                                />
                            ) : (
                                <LemonTableLink
                                    to={urls.dataWarehouseSource(`self-managed-${row.table.id}`)}
                                    title={row.table.name}
                                />
                            ),
                    },
                    {
                        key: 'actions',
                        render: (_, row) => (
                            <div className="flex flex-row justify-end">
                                {row.kind === 'direct' ? (
                                    sourceReloadingById[row.source.id] ? (
                                        <Spinner />
                                    ) : (
                                        <>
                                            <LemonButton
                                                data-attr={`reload-data-warehouse-${row.source.source_type}`}
                                                onClick={() => reloadSource(row.source)}
                                            >
                                                Reload
                                            </LemonButton>
                                            <LemonButton
                                                status="danger"
                                                data-attr={`delete-data-warehouse-${row.source.source_type}`}
                                                onClick={() => {
                                                    LemonDialog.open({
                                                        title: 'Delete data source?',
                                                        description:
                                                            'Are you sure you want to delete this data source? All related tables will be deleted.',
                                                        primaryButton: {
                                                            children: 'Delete',
                                                            status: 'danger',
                                                            onClick: () => deleteSource(row.source),
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
                                    )
                                ) : (
                                    <>
                                        <LemonButton
                                            data-attr={`refresh-data-warehouse-${row.table.name}`}
                                            onClick={() => refreshSelfManagedTableSchema(row.table.id)}
                                        >
                                            Update schema from source
                                        </LemonButton>
                                        <LemonButton
                                            status="danger"
                                            data-attr={`delete-data-warehouse-${row.table.name}`}
                                            onClick={() => {
                                                LemonDialog.open({
                                                    title: 'Delete table?',
                                                    description:
                                                        'Table deletion cannot be undone. All views and joins related to this table will be deleted.',
                                                    primaryButton: {
                                                        children: 'Delete',
                                                        status: 'danger',
                                                        onClick: () => deleteSelfManagedTable(row.table.id),
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
