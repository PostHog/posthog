import { IconDatabase } from '@posthog/icons'
import { LemonButton, LemonTag, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { DatabaseTableTree } from 'lib/components/DatabaseTableTree/DatabaseTableTree'
import { PageHeader } from 'lib/components/PageHeader'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconDataObject, IconSettings } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { DatabaseTable } from 'scenes/data-management/database/DatabaseTable'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { NodeKind } from '~/queries/schema'
import { ProductKey } from '~/types'

import { dataWarehouseSceneLogic } from './dataWarehouseSceneLogic'
import SourceModal from './SourceModal'

export const scene: SceneExport = {
    component: DataWarehouseExternalScene,
    logic: dataWarehouseSceneLogic,
}

export function DataWarehouseExternalScene(): JSX.Element {
    const {
        shouldShowEmptyState,
        shouldShowProductIntroduction,
        isSourceModalOpen,
        tables,
        posthogTables,
        savedQueriesFormatted,
        selectedRow,
    } = useValues(dataWarehouseSceneLogic)
    const { toggleSourceModal, selectRow } = useActions(dataWarehouseSceneLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <div>
            <PageHeader
                title={
                    <div className="flex items-center gap-2">
                        Data Warehouse
                        <LemonTag type="warning" className="uppercase">
                            Beta
                        </LemonTag>
                    </div>
                }
                buttons={
                    featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE_EXTERNAL_LINK] ? (
                        <LemonButton
                            type="primary"
                            sideAction={{
                                icon: <IconSettings />,
                                onClick: () => router.actions.push(urls.dataWarehouseSettings()),
                                'data-attr': 'saved-insights-new-insight-dropdown',
                            }}
                            data-attr="new-data-warehouse-easy-link"
                            key={'new-data-warehouse-easy-link'}
                            onClick={() => toggleSourceModal()}
                        >
                            Link Source
                        </LemonButton>
                    ) : !(shouldShowProductIntroduction || shouldShowEmptyState) ? (
                        <LemonButton type="primary" to={urls.dataWarehouseTable()} data-attr="new-data-warehouse-table">
                            New table
                        </LemonButton>
                    ) : undefined
                }
                caption={
                    <div>
                        These are external data sources you can query under SQL insights with{' '}
                        <Link to="https://posthog.com/manual/hogql" target="_blank">
                            HogQL
                        </Link>
                        . Connect your own tables from S3 to query data from outside PostHog.{' '}
                        <Link to="https://posthog.com/docs/data/data-warehouse">Learn more</Link>
                    </div>
                }
            />
            {(shouldShowProductIntroduction || shouldShowEmptyState) && (
                <ProductIntroduction
                    productName={'Data Warehouse'}
                    thingName={'table'}
                    description={
                        'Bring your production database, revenue data, CRM contacts or any other data into PostHog.'
                    }
                    action={() =>
                        featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE_EXTERNAL_LINK]
                            ? toggleSourceModal()
                            : router.actions.push(urls.dataWarehouseTable())
                    }
                    isEmpty={shouldShowEmptyState}
                    docsURL="https://posthog.com/docs/data/data-warehouse"
                    productKey={ProductKey.DATA_WAREHOUSE}
                />
            )}
            <div className="grid md:grid-cols-3">
                <div className="sm:col-span-3 md:col-span-1">
                    <DatabaseTableTree
                        onSelectRow={selectRow}
                        items={[
                            {
                                name: 'External',
                                items: tables.map((table) => ({
                                    table: table,
                                    icon: <IconDatabase />,
                                })),
                            },
                            {
                                name: 'PostHog',
                                items: posthogTables.map((table) => ({
                                    table: table,
                                    icon: <IconDatabase />,
                                })),
                            },
                            {
                                name: 'Views',
                                items: savedQueriesFormatted.map((table) => ({
                                    table: table,
                                    icon: <IconDataObject />,
                                })),
                            },
                        ]}
                    />
                </div>
                {selectedRow && (
                    <div className="px-4 py-3 col-span-2">
                        <div className="flex flex-row justify-between items-center">
                            <h3>{selectedRow.name}</h3>
                            <Link
                                to={urls.insightNew(
                                    undefined,
                                    undefined,
                                    JSON.stringify({
                                        kind: NodeKind.DataTableNode,
                                        full: true,
                                        source: {
                                            kind: NodeKind.HogQLQuery,
                                            // TODO: Use `hogql` tag?
                                            query: `SELECT ${selectedRow.columns
                                                .filter(({ table, fields, chain }) => !table && !fields && !chain)
                                                .map(({ key }) => key)} FROM ${selectedRow.name} LIMIT 100`,
                                        },
                                    })
                                )}
                            >
                                <LemonButton type="primary">Query</LemonButton>
                            </Link>
                        </div>
                        <div className="flex flex-col">
                            {selectedRow.external_data_source ? (
                                <></>
                            ) : (
                                <>
                                    <span className="card-secondary mt-2">Files URL pattern</span>
                                    <span>{selectedRow.url_pattern}</span>
                                </>
                            )}

                            <span className="card-secondary mt-2">File format</span>
                            <span>{selectedRow.format}</span>
                        </div>

                        <div className="mt-2">
                            <span className="card-secondary">Columns</span>
                            <DatabaseTable table={selectedRow.name} tables={tables} />
                        </div>
                    </div>
                )}
            </div>
            <SourceModal isOpen={isSourceModalOpen} onClose={() => toggleSourceModal(false)} />
        </div>
    )
}
