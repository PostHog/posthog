import { useActions, useValues } from 'kea'

import { AccessDenied } from 'lib/components/AccessDenied'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import {
    MaterializationRunsTable,
    MaterializationStatusCard,
} from 'scenes/data-warehouse/saved_queries/MaterializationStatusPanel'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { NodeDetailHeader } from './NodeDetailHeader'
import type { NodeDetailSceneLogicProps, NodeDetailTab } from './nodeDetailSceneLogic'
import { nodeDetailSceneLogic } from './nodeDetailSceneLogic'
import { NodeDetailLineage } from './tabs/NodeDetailLineage'
import { NodeDetailQuery } from './tabs/NodeDetailQuery'

export const scene: SceneExport<NodeDetailSceneLogicProps> = {
    component: NodeDetailScene,
    logic: nodeDetailSceneLogic,
    productKey: ProductKey.DATA_WAREHOUSE_SAVED_QUERY,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

export function NodeDetailScene({ id }: NodeDetailSceneLogicProps): JSX.Element {
    const { node, nodeLoading, hasMaterialization, activeTab } = useValues(nodeDetailSceneLogic({ id }))
    const { setTab } = useActions(nodeDetailSceneLogic({ id }))

    if (!userHasAccess(AccessControlResourceType.WarehouseObjects, AccessControlLevel.Viewer)) {
        return (
            <AccessDenied reason="You don't have access to Data warehouse tables & views, so this page isn't available." />
        )
    }

    const showQueryTab = !nodeLoading && !!node && node.type !== 'table'
    const showRunsTab = hasMaterialization && !!node?.saved_query_id

    const tabs = [
        ...(showQueryTab
            ? [
                  {
                      key: 'query' as NodeDetailTab,
                      label: 'Query',
                      content: <NodeDetailQuery id={id} />,
                  },
              ]
            : []),
        {
            key: 'lineage' as NodeDetailTab,
            label: 'Lineage',
            content: <NodeDetailLineage id={id} />,
        },
        ...(showRunsTab
            ? [
                  {
                      key: 'runs' as NodeDetailTab,
                      label: 'Run history',
                      content: <MaterializationRunsTable viewId={node.saved_query_id as string} />,
                  },
              ]
            : []),
    ]
    const effectiveTab = tabs.some((tab) => tab.key === activeTab) ? activeTab : tabs[0]?.key

    return (
        <SceneContent>
            <NodeDetailHeader id={id} />
            {showRunsTab && (
                <MaterializationStatusCard
                    viewId={node.saved_query_id as string}
                    kind={node.type === 'endpoint' ? 'endpoint' : 'view'}
                />
            )}
            <LemonTabs activeKey={effectiveTab} onChange={(tab) => setTab(tab)} tabs={tabs} />
        </SceneContent>
    )
}
