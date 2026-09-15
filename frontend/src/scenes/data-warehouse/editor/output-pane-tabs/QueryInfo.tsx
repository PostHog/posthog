import { useActions, useMountedLogic, useValues } from 'kea'

import { IconExternal, IconTarget } from '@posthog/icons'
import { LemonBanner, LemonTable, Link, Spinner, lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'
import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'
import { MaterializationStatusPanel } from 'scenes/data-warehouse/saved_queries/MaterializationStatusPanel'
import { urls } from 'scenes/urls'

import { DataModelingNode, DataWarehouseSavedQuery } from '~/types'

import { LineageGraph } from 'products/data_modeling/frontend/lineage/LineageGraph'
import { NODE_TYPE_TAG_SETTINGS } from 'products/data_modeling/frontend/lineage/nodeStyles'
import { syncIntervalToShorthand } from 'products/data_warehouse/frontend/utils'

import { sqlEditorLogic } from '../sqlEditorLogic'
import { infoTabLogic } from './infoTabLogic'
import { ViewDataQualityChecks } from './ViewDataQualityChecks'

interface QueryInfoProps {
    tabId: string
    view?: DataWarehouseSavedQuery | null
    tabbed?: boolean
}

export function QueryInfo({ tabId, view, tabbed = false }: QueryInfoProps): JSX.Element {
    const {
        editingView,
        upstream: loadedUpstream,
        upstreamLoading,
        upstreamLoadFailed,
        upstreamViewMode,
    } = useValues(sqlEditorLogic)
    const targetView = view ?? editingView
    // Mounting it loads the lineage for the view being edited.
    const infoLogic = infoTabLogic({ tabId, viewId: targetView?.id })
    useMountedLogic(infoLogic)
    const { activeSection, lineageVisited } = useValues(infoLogic)
    const { setActiveSection } = useActions(infoLogic)
    const { saveAsView, setUpstreamViewMode, editView, loadUpstream } = useActions(sqlEditorLogic)
    // The loaded lineage is shared across views, so only use it when it was loaded for this one.
    const upstream = loadedUpstream && targetView && loadedUpstream.modelId === targetView.id ? loadedUpstream : null
    const { featureFlags } = useValues(featureFlagLogic)

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

    if (initialDataWarehouseSavedQueryLoading && !targetView) {
        return (
            <div className="w-full h-full flex items-center justify-center">
                <Spinner className="text-lg" />
            </div>
        )
    }

    return (
        <div className="overflow-auto" data-attr="sql-editor-sidebar-query-info-pane">
            {tabbed && targetView && (
                <LemonTabs
                    activeKey={activeSection}
                    onChange={setActiveSection}
                    tabs={[
                        { key: 'materialization', label: 'Materialization' },
                        { key: 'lineage', label: 'Lineage' },
                        ...(featureFlags[FEATURE_FLAGS.DATA_QUALITY_CHECKS]
                            ? [{ key: 'quality' as const, label: 'Data quality' }]
                            : []),
                    ]}
                />
            )}
            <div className="flex flex-col flex-1 gap-4">
                {targetView ? (
                    <>
                        <div className={tabbed && activeSection !== 'materialization' ? 'hidden' : undefined}>
                            <MaterializationStatusPanel
                                viewId={targetView.id}
                                hideTitle={tabbed}
                                showRunActions={!tabbed}
                            />
                        </div>
                        {featureFlags[FEATURE_FLAGS.DATA_QUALITY_CHECKS] && (
                            <div className={tabbed && activeSection !== 'quality' ? 'hidden' : undefined}>
                                <ViewDataQualityChecks view={targetView} />
                            </div>
                        )}
                    </>
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
                <div className={tabbed && activeSection !== 'lineage' ? 'hidden' : 'flex flex-col gap-4'}>
                    {/* The response always carries the model itself, so its node count is never zero.
                        An empty edge list is what says nothing connects to this model. */}
                    {tabbed &&
                        targetView &&
                        !upstreamLoading &&
                        !upstreamLoadFailed &&
                        upstream?.edges.length === 0 && (
                            <p className="text-secondary py-8 text-center">No connected models yet.</p>
                        )}
                    {targetView && upstreamLoading && <Spinner />}
                    {targetView && upstreamLoadFailed && !upstreamLoading && (
                        <LemonBanner
                            type="warning"
                            action={{ children: 'Retry', onClick: () => loadUpstream(targetView.id) }}
                        >
                            Couldn't load this view's lineage.
                        </LemonBanner>
                    )}
                    {(!tabbed || lineageVisited) && upstream && targetView && upstream.edges.length > 0 && (
                        <>
                            <div>
                                <div className="flex flex-wrap items-center justify-between gap-3">
                                    <div>
                                        <h3 className="mb-1">Lineage</h3>
                                        <p className="text-xs mb-0">
                                            Tables and views connected to this query — what it reads from and what
                                            builds on it.
                                        </p>
                                    </div>
                                    <div className="flex flex-wrap items-center gap-2">
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
                                                    sync_interval
                                                        ? ` every ${syncIntervalToShorthand(sync_interval)}`
                                                        : ''
                                                }`
                                            },
                                        },
                                    ]}
                                    dataSource={upstream.nodes}
                                />
                            ) : (
                                <div
                                    className={
                                        tabbed
                                            ? 'h-[min(45vh,500px)] border border-border rounded-md overflow-hidden'
                                            : 'h-[500px] border border-border rounded-md overflow-hidden'
                                    }
                                >
                                    <LineageGraph
                                        nodes={upstream.nodes}
                                        edges={upstream.edges}
                                        currentNodeId={currentNodeId}
                                        variant="full"
                                        fitViewOptions={tabbed ? { maxZoom: 1 } : undefined}
                                        interactive
                                        showControls
                                        showMinimap
                                        panels={
                                            <LemonButton
                                                type="secondary"
                                                size="small"
                                                to={urls.models('lineage')}
                                                targetBlank
                                                tooltip="Open the full graph"
                                                aria-label="Open the full graph"
                                                icon={<IconExternal />}
                                            />
                                        }
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
        </div>
    )
}
