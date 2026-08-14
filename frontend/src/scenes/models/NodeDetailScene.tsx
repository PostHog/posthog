import { useValues } from 'kea'

import { AccessDenied } from 'lib/components/AccessDenied'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { DataQualityChecksPanel } from 'products/data_quality/frontend/DataQualityChecksPanel'

import { NodeDetailDetails } from './NodeDetailDetails'
import { NodeDetailHeader } from './NodeDetailHeader'
import { NodeDetailMaterialization } from './NodeDetailMaterialization'
import type { NodeDetailSceneLogicProps } from './nodeDetailSceneLogic'
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
    const { node, nodeLoading, hasMaterialization, savedQuery } = useValues(nodeDetailSceneLogic({ id }))
    const { featureFlags } = useValues(featureFlagLogic)

    if (!userHasAccess(AccessControlResourceType.WarehouseObjects, AccessControlLevel.Viewer)) {
        return (
            <AccessDenied reason="You don't have access to Data warehouse tables & views, so this page isn't available." />
        )
    }

    return (
        <SceneContent>
            <NodeDetailHeader id={id} />
            {!nodeLoading && node && <NodeDetailDetails id={id} />}
            {!nodeLoading && node && node.type !== 'table' && <NodeDetailQuery id={id} />}
            <NodeDetailLineage id={id} />
            {hasMaterialization && <NodeDetailMaterialization id={id} />}
            {featureFlags[FEATURE_FLAGS.DATA_QUALITY_CHECKS] && node?.saved_query_id && (
                <DataQualityChecksPanel
                    subjectType="view"
                    subjectId={node.saved_query_id}
                    columns={savedQuery?.columns ?? []}
                    showGateToggle={!!savedQuery?.is_materialized}
                />
            )}
        </SceneContent>
    )
}
