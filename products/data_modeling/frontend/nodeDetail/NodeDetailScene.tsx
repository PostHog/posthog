import { useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { AccessDenied } from 'lib/components/AccessDenied'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { NotFound } from 'lib/components/NotFound'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { ProductKey } from '~/queries/schema/schema-general'
import { ActivityScope, AccessControlLevel, AccessControlResourceType } from '~/types'

import { ModelMetadata } from './ModelMetadata'
import { NodeDetailHeader } from './NodeDetailHeader'
import { NodeDetailLineage } from './NodeDetailLineage'
import { NodeDetailMaterialization } from './NodeDetailMaterialization'
import { NodeDetailOverview } from './NodeDetailOverview'
import { NodeDetailQuery } from './NodeDetailQuery'
import type { NodeDetailSceneLogicProps, NodeDetailSceneTab } from './nodeDetailSceneLogic'
import { nodeDetailSceneLogic } from './nodeDetailSceneLogic'
import { NodeDetailTests } from './NodeDetailTests'
import { NodeDetailTestsTabLabel } from './NodeDetailTestsTabLabel'

export const scene: SceneExport<NodeDetailSceneLogicProps> = {
    component: NodeDetailScene,
    logic: nodeDetailSceneLogic,
    productKey: ProductKey.DATA_WAREHOUSE_SAVED_QUERY,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

const TAB_LABELS: Record<NodeDetailSceneTab, string> = {
    query: 'Query',
    lineage: 'Lineage',
    materialization: 'Materialization',
    tests: 'Data quality',
    history: 'History',
}

function tabLabel(tab: NodeDetailSceneTab, savedQueryId: string | null | undefined): JSX.Element | string {
    if (tab === 'tests' && savedQueryId) {
        return <NodeDetailTestsTabLabel subjectId={savedQueryId} />
    }
    return TAB_LABELS[tab]
}

export function NodeDetailScene({ id }: NodeDetailSceneLogicProps): JSX.Element {
    const { node, savedQuery, savedQueryLoading, nodeLoading, availableTabs, effectiveTab, visitedTabs } = useValues(
        nodeDetailSceneLogic({ id })
    )

    if (!userHasAccess(AccessControlResourceType.WarehouseObjects, AccessControlLevel.Viewer)) {
        return (
            <AccessDenied reason="You don't have access to Data warehouse tables & views, so this page isn't available." />
        )
    }

    if (!node) {
        if (nodeLoading) {
            return (
                <SceneContent>
                    <NodeDetailHeader id={id} />
                    <LemonSkeleton className="h-10 w-96" />
                    <LemonSkeleton className="h-64 w-full" />
                </SceneContent>
            )
        }
        return <NotFound object="model" />
    }

    const savedQueryId = node.saved_query_id

    const tabPanel = (tab: NodeDetailSceneTab): JSX.Element => {
        switch (tab) {
            case 'query':
                return <NodeDetailQuery id={id} />
            case 'lineage':
                return <NodeDetailLineage id={id} />
            case 'materialization':
                return <NodeDetailMaterialization id={id} />
            case 'history':
                return (
                    <ActivityLog
                        scope={[ActivityScope.DATA_WAREHOUSE_SAVED_QUERY, ActivityScope.DATA_QUALITY_CHECK]}
                        id={savedQueryId ?? ''}
                    />
                )
            case 'tests':
                return <NodeDetailTests id={id} subjectId={savedQueryId ?? ''} />
        }
    }

    const tabs: LemonTab<NodeDetailSceneTab>[] = availableTabs.map((tab) => ({
        key: tab,
        label: tabLabel(tab, savedQueryId),
        link: urls.nodeDetail(id, tab),
        'data-attr': `node-detail-${tab}-tab`,
    }))

    return (
        <SceneContent>
            <NodeDetailHeader id={id} />
            {/* A node row's timestamps describe the node, not the model: editing the
                description here patches the node and bumps its updated_at while the saved
                query stays untouched. So they stand in only for a node that has no saved
                query, and a failed load says nothing rather than the node's dates. */}
            <NodeDetailOverview
                id={id}
                metadata={
                    <ModelMetadata
                        createdBy={savedQuery?.created_by}
                        createdAt={node.saved_query_id ? savedQuery?.created_at : node.created_at}
                        updatedAt={node.saved_query_id ? undefined : node.updated_at}
                        loading={!!node.saved_query_id && savedQueryLoading && !savedQuery}
                    />
                }
            />
            {!effectiveTab ? (
                <LemonSkeleton className="h-10 w-96" />
            ) : (
                // The bar only: panels are siblings below so a visited one stays mounted, keeping
                // materialization drafts, the check editor and the graph viewport across switches.
                availableTabs.length > 1 && <LemonTabs activeKey={effectiveTab} tabs={tabs} sceneInset />
            )}
            {availableTabs
                // Always render the active tab, even one not yet visited: if a shrinking tab set
                // (e.g. the checks flag turned off while Tests was open) falls back to a tab the
                // user never opened, it would otherwise show a blank body.
                .filter((tab) =>
                    tab === 'history' ? tab === effectiveTab : visitedTabs.includes(tab) || tab === effectiveTab
                )
                .map((tab) => (
                    <div key={tab} className={tab === effectiveTab ? 'flex flex-col flex-1' : 'hidden'}>
                        {tabPanel(tab)}
                    </div>
                ))}
        </SceneContent>
    )
}
