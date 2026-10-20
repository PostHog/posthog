import { useValues } from 'kea'

import { Button } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { materializationJobsLogic } from 'scenes/data-warehouse/saved_queries/materializationJobsLogic'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType, DataModelingNode, DataWarehouseSavedQuery } from '~/types'

import { nodeEndpointUrl } from 'products/data_modeling/frontend/endpointModelName'
import { MaterializationRunActions } from 'products/data_warehouse/frontend/shared/components/MaterializationRunActions'

export function QuillNodeDetailActions({
    node,
    savedQuery,
}: {
    node: DataModelingNode
    savedQuery: DataWarehouseSavedQuery
}): JSX.Element {
    const { hasMaterializationChanges, savingMaterialization } = useValues(
        materializationJobsLogic({ viewId: savedQuery.id, kind: node.type === 'endpoint' ? 'endpoint' : 'view' })
    )
    const editDisabledReason =
        hasMaterializationChanges || savingMaterialization
            ? 'Save or discard your changes first'
            : getAccessControlDisabledReason(
                  AccessControlResourceType.WarehouseObjects,
                  AccessControlLevel.Editor,
                  savedQuery.user_access_level
              )
    return (
        <>
            {node.type === 'endpoint' ? (
                <Button variant="outline" render={<LinkPrimitive to={nodeEndpointUrl(node)} />}>
                    Open endpoint
                </Button>
            ) : (
                <AccessControlAction
                    resourceType={AccessControlResourceType.WarehouseObjects}
                    minAccessLevel={AccessControlLevel.Editor}
                    userAccessLevel={savedQuery.user_access_level}
                >
                    <Button
                        variant="outline"
                        render={
                            <LinkPrimitive
                                to={editDisabledReason ? undefined : urls.sqlEditor({ view_id: savedQuery.id })}
                            />
                        }
                        disabledReason={editDisabledReason ?? undefined}
                        data-attr="node-detail-edit-in-sql-editor"
                    >
                        Edit in SQL editor
                    </Button>
                </AccessControlAction>
            )}
            <MaterializationRunActions viewId={savedQuery.id} kind={node.type === 'endpoint' ? 'endpoint' : 'view'} />
        </>
    )
}
