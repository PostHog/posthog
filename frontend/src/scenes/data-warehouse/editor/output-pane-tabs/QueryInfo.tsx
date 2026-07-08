import { useActions, useValues } from 'kea'

import { IconTarget } from '@posthog/icons'
import { LemonTable, Link, Spinner, lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'
import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'
import { MaterializationStatusPanel } from 'scenes/data-warehouse/saved_queries/MaterializationStatusPanel'

import { DataModelingNode, DataWarehouseSavedQuery } from '~/types'

import { LineageGraph } from 'products/data_modeling/frontend/lineage/LineageGraph'
import { NODE_TYPE_TAG_SETTINGS } from 'products/data_modeling/frontend/lineage/nodeStyles'
import { syncIntervalToShorthand } from 'products/data_warehouse/frontend/utils'

import { sqlEditorLogic } from '../sqlEditorLogic'
import { infoTabLogic } from './infoTabLogic'

interface QueryInfoProps {
    tabId: string
    view?: DataWarehouseSavedQuery | null
}

export function QueryInfo({ tabId, view }: QueryInfoProps): JSX.Element {
    const { editingView, upstream, upstreamViewMode } = useValues(sqlEditorLogic)
    const targetView = view ?? editingView
    const infoLogic = infoTabLogic({ tabId, viewId: targetView?.id })
    const { sourceTableItems } = useValues(infoLogic)
    const { saveAsView, setUpstreamViewMode, editView } = useActions(sqlEditorLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const isLineageDependencyViewEnabled = featureFlags[FEATURE_FLAGS.LINEAGE_DEPENDENCY_VIEW]

    const currentNodeId = upstream?.nodes.find((n) => n.saved_query_id && n.saved_query_id === targetView?.id)?.id
    const openInEditor = async (node: DataModelingNode): Promise<void> => {
        if (!node.saved_query_id) {
            return
        }
        try {
            const savedQuery = await api.dataWarehouseSavedQueries.get(node.saved_query_id)
            if (savedQuery?.query?.query) {
                editView(savedQuery.query.query, savedQuery)
            }
        } catch {
            lemonToast.error('Failed to load view details')
        }
    }

    const { updatingDataWarehouseSavedQuery, initialDataWarehouseSavedQueryLoading } =
        useValues(dataWarehouseViewsLogic)

    if (initialDataWarehouseSavedQueryLoading) {
        return (
            <div className="w-full h-full flex items-center justify-center">
                <Spinner className="text-lg" />
            </div>
        )
    }

    return (
        <div className="overflow-auto" data-attr="sql-editor-sidebar-query-info-pane">
            <div className="flex flex-col flex-1 gap-4">
                {targetView ? (
                    <MaterializationStatusPanel viewId={targetView.id} />
                ) : (
                    <div>
                        <div className="flex flex-row items-center gap-2">
                            <h3 className="mb-0">Materialization</h3>
                            <LemonTag type="warning">BETA</LemonTag>
                        </div>
                        <p className="text-xs">
                            Materialized views are a way to pre-compute data in your data warehouse. This allows you to
                            run queries faster and more efficiently.
                            <br />
                            <Link
                                data-attr="materializing-help"
                                to="https://posthog.com/docs/data-warehouse/views#materializing-and-scheduling-a-view"
                                target="_blank"
                            >
                                Learn more about materialization
                            </Link>
                            .
                        </p>
                        <LemonButton
                            size="small"
                            onClick={() => saveAsView({ materializeAfterSave: true })}
                            type="primary"
                            loading={updatingDataWarehouseSavedQuery}
                        >
                            Save and materialize
                        </LemonButton>
                    </div>
                )}
                {!isLineageDependencyViewEnabled && (
                    <>
                        <div>
                            <h3>Dependencies</h3>
                            <p className="text-xs">Dependencies are tables that this query uses.</p>
                        </div>
                        <LemonTable
                            size="small"
                            columns={[
                                {
                                    key: 'Name',
                                    title: 'Name',
                                    render: (_, { name }) => name,
                                },
                                {
                                    key: 'Type',
                                    title: 'Type',
                                    render: (_, { type }) => type,
                                },
                                {
                                    key: 'Status',
                                    title: 'Status',
                                    render: (_, { type, status, last_run_at }) => {
                                        if (type === 'source') {
                                            return (
                                                <Tooltip title="This is a source table, so it doesn't have a status">
                                                    <span className="text-secondary">N/A</span>
                                                </Tooltip>
                                            )
                                        }
                                        if (last_run_at === 'never' && !status) {
                                            return (
                                                <Tooltip title="This is a view, so it's always available with the latest data">
                                                    <span className="text-secondary">Available</span>
                                                </Tooltip>
                                            )
                                        }
                                        return status
                                    },
                                },
                                {
                                    key: 'Last run at',
                                    title: 'Last run at',
                                    render: (_, { type, last_run_at, status }) => {
                                        if (type === 'source') {
                                            return (
                                                <Tooltip title="This is a source table, so it is never run">
                                                    <span className="text-secondary">N/A</span>
                                                </Tooltip>
                                            )
                                        }
                                        if (last_run_at === 'never' && !status) {
                                            return (
                                                <Tooltip title="This is a view, so it is never run">
                                                    <span className="text-secondary">N/A</span>
                                                </Tooltip>
                                            )
                                        }
                                        return humanFriendlyDetailedTime(last_run_at)
                                    },
                                },
                            ]}
                            dataSource={sourceTableItems}
                        />
                    </>
                )}

                {upstream && targetView && upstream.nodes.length > 0 && isLineageDependencyViewEnabled && (
                    <>
                        <div>
                            <div className="flex items-center justify-between">
                                <div>
                                    <h3 className="mb-1">Lineage</h3>
                                    <p className="text-xs mb-0">
                                        Tables and views connected to this query — what it reads from and what builds on
                                        it.
                                    </p>
                                </div>
                                <LemonSegmentedButton
                                    value={upstreamViewMode}
                                    onChange={(mode) => setUpstreamViewMode(mode)}
                                    options={[
                                        {
                                            value: 'graph',
                                            label: 'Graph',
                                        },
                                        {
                                            value: 'table',
                                            label: 'Table',
                                        },
                                    ]}
                                    size="small"
                                />
                            </div>
                        </div>
                        {upstreamViewMode === 'table' ? (
                            <LemonTable
                                size="small"
                                columns={[
                                    {
                                        key: 'name',
                                        title: 'Name',
                                        render: (_, { name }) => (
                                            <div className="flex items-center gap-1">
                                                {name === targetView?.name && (
                                                    <Tooltip
                                                        placement="right"
                                                        title="This is the currently viewed query"
                                                    >
                                                        <IconTarget className="text-warning" />
                                                    </Tooltip>
                                                )}
                                                {name}
                                            </div>
                                        ),
                                    },
                                    {
                                        key: 'type',
                                        title: 'Type',
                                        render: (_, { type }) => NODE_TYPE_TAG_SETTINGS[type].label,
                                    },
                                    {
                                        key: 'upstream',
                                        title: 'Direct Upstream',
                                        render: (_, node) => {
                                            const upstreamNodes = upstream.edges
                                                .filter((edge) => edge.target_id === node.id)
                                                .map((edge) => upstream.nodes.find((n) => n.id === edge.source_id))
                                                .filter((n): n is DataModelingNode => n !== undefined)

                                            if (upstreamNodes.length === 0) {
                                                return <span className="text-secondary">None</span>
                                            }

                                            return (
                                                <div className="flex flex-wrap gap-1">
                                                    {upstreamNodes.map((upstreamNode) => (
                                                        <LemonTag key={upstreamNode.id} type="primary">
                                                            {upstreamNode.name}
                                                        </LemonTag>
                                                    ))}
                                                </div>
                                            )
                                        },
                                    },
                                    {
                                        key: 'last_run_at',
                                        title: 'Last Run At',
                                        render: (_, { last_run_at, sync_interval }) => {
                                            if (!last_run_at) {
                                                return 'On demand'
                                            }
                                            return `${humanFriendlyDetailedTime(last_run_at)}${
                                                sync_interval ? ` every ${syncIntervalToShorthand(sync_interval)}` : ''
                                            }`
                                        },
                                    },
                                ]}
                                dataSource={upstream.nodes}
                            />
                        ) : (
                            <div className="h-[500px] border border-border rounded-md overflow-hidden">
                                <LineageGraph
                                    nodes={upstream.nodes}
                                    edges={upstream.edges}
                                    currentNodeId={currentNodeId}
                                    variant="full"
                                    interactive
                                    showControls
                                    showMinimap
                                    nodeCallbacks={(node) => ({
                                        onEdit:
                                            node.type !== 'table' && node.id !== currentNodeId
                                                ? () => void openInEditor(node)
                                                : undefined,
                                    })}
                                />
                            </div>
                        )}
                    </>
                )}
            </div>
        </div>
    )
}
