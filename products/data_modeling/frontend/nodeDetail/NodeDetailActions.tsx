import { LemonButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { DataModelingNode, DataWarehouseSavedQuery } from '~/types'

import { nodeEndpointUrl } from 'products/data_modeling/frontend/endpointModelName'
import { MaterializationRunActions } from 'products/data_warehouse/frontend/shared/components/MaterializationRunActions'

import { NodeDetailQueryEditorActions } from './NodeDetailQueryEditorActions'
import { QuillNodeDetailActions } from './QuillNodeDetailActions'

export function NodeDetailActions({
    id,
    node,
    savedQuery,
}: {
    id: string
    node: DataModelingNode
    savedQuery: DataWarehouseSavedQuery
}): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    if (todayRailNav) {
        return <QuillNodeDetailActions id={id} node={node} savedQuery={savedQuery} />
    }
    return (
        <>
            {node.type === 'endpoint' ? (
                <LemonButton type="secondary" size="small" to={nodeEndpointUrl(node)}>
                    Open endpoint
                </LemonButton>
            ) : (
                <NodeDetailQueryEditorActions id={id} />
            )}
            <MaterializationRunActions viewId={savedQuery.id} kind={node.type === 'endpoint' ? 'endpoint' : 'view'} />
        </>
    )
}
