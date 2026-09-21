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

import { ModelMetadata } from 'products/data_modeling/frontend/nodeDetail/ModelMetadata'

import { NodeDetailHeader } from './NodeDetailHeader'
import { NodeDetailOverview } from './NodeDetailOverview'
import type {
    NodeDetailDataQualitySubject,
    NodeDetailSceneLogicProps,
    NodeDetailSceneTab,
} from './nodeDetailSceneLogic'
import { nodeDetailSceneLogic } from './nodeDetailSceneLogic'
import { NodeDetailLineage } from './tabs/NodeDetailLineage'
import { NodeDetailMaterialization } from './tabs/NodeDetailMaterialization'
import { NodeDetailQuery } from './tabs/NodeDetailQuery'
import { NodeDetailTests } from './tabs/NodeDetailTests'
import { NodeDetailTestsTabLabel } from './tabs/NodeDetailTestsTabLabel'

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

function tabLabel(
    tab: NodeDetailSceneTab,
    dataQualitySubject: NodeDetailDataQualitySubject | null
): JSX.Element | string {
    if (tab === 'tests' && dataQualitySubject) {
        return <NodeDetailTestsTabLabel {...dataQualitySubject} />
    }
    return TAB_LABELS[tab]
}

export function NodeDetailScene({ id }: NodeDetailSceneLogicProps): JSX.Element {
    const {
        node,
        savedQuery,
        savedQueryLoading,
        nodeLoading,
        availableTabs,
        effectiveTab,
        visitedTabs,
        dataQualitySubject,
        tableDetails,
        tableDetailsLoading,
    } = useValues(nodeDetailSceneLogic({ id }))

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
                return dataQualitySubject ? <NodeDetailTests id={id} {...dataQualitySubject} /> : <></>
        }
    }

    const tabs: LemonTab<NodeDetailSceneTab>[] = availableTabs.map((tab) => ({
        key: tab,
        label: tabLabel(tab, dataQualitySubject),
        link: urls.nodeDetail(id, tab),
        'data-attr': `node-detail-${tab}-tab`,
    }))

    return (
        <SceneContent>
            <NodeDetailHeader id={id} />
            <NodeDetailOverview
                id={id}
                metadata={
                    <ModelMetadata
                        createdBy={
                            node.saved_query_id
                                ? savedQuery?.created_by
                                : tableDetails?.source
                                  ? undefined
                                  : tableDetails?.table.created_by
                        }
                        createdByEmail={node.saved_query_id ? undefined : tableDetails?.source?.created_by}
                        createdByLabel={node.origin === 'posthog' ? 'PostHog' : undefined}
                        createdAt={
                            node.saved_query_id
                                ? savedQuery?.created_at
                                : node.origin === 'posthog'
                                  ? node.created_at
                                  : (tableDetails?.source?.created_at ?? tableDetails?.table.created_at ?? node.created_at)
                        }
                        updatedAt={node.saved_query_id || tableDetails ? undefined : node.updated_at}
                        loading={
                            (!!node.saved_query_id && savedQueryLoading && !savedQuery) ||
                            (!!node.warehouse_table_id && tableDetailsLoading && !tableDetails)
                        }
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
