import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { materializationJobsLogic } from 'scenes/data-warehouse/saved_queries/materializationJobsLogic'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType, DataModelingNode, DataWarehouseSavedQuery } from '~/types'

import { nodeEndpointUrl } from 'products/data_modeling/frontend/endpointModelName'
import { MaterializationRunActions } from 'products/data_warehouse/frontend/shared/components/MaterializationRunActions'

export function NodeDetailActions({
    node,
    savedQuery,
}: {
    node: DataModelingNode
    savedQuery: DataWarehouseSavedQuery
}): JSX.Element {
    const { hasMaterializationChanges, savingMaterialization } = useValues(
        materializationJobsLogic({ viewId: savedQuery.id, kind: node.type === 'endpoint' ? 'endpoint' : 'view' })
    )
    return (
        <>
            {node.type === 'endpoint' ? (
                <LemonButton type="secondary" size="small" to={nodeEndpointUrl(node)}>
                    Open endpoint
                </LemonButton>
            ) : (
                <AccessControlAction
                    resourceType={AccessControlResourceType.WarehouseObjects}
                    minAccessLevel={AccessControlLevel.Editor}
                    userAccessLevel={savedQuery.user_access_level}
                >
                    <LemonButton
                        type="secondary"
                        size="small"
                        to={urls.sqlEditor({ view_id: savedQuery.id })}
                        disabledReason={
                            (hasMaterializationChanges || savingMaterialization) && 'Save or discard your changes first'
                        }
                        data-attr="node-detail-edit-in-sql-editor"
                    >
                        Edit in SQL editor
                    </LemonButton>
                </AccessControlAction>
            )}
            <MaterializationRunActions viewId={savedQuery.id} kind={node.type === 'endpoint' ? 'endpoint' : 'view'} />
        </>
    )
}
