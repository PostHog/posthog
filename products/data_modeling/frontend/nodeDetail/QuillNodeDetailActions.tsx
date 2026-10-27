import { Button } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { DataModelingNode, DataWarehouseSavedQuery } from '~/types'

import { nodeEndpointUrl } from 'products/data_modeling/frontend/endpointModelName'
import { MaterializationRunActions } from 'products/data_warehouse/frontend/shared/components/MaterializationRunActions'

import { QuillNodeDetailQueryEditorActions } from './QuillNodeDetailQueryEditorActions'

export function QuillNodeDetailActions({
    id,
    node,
    savedQuery,
}: {
    id: string
    node: DataModelingNode
    savedQuery: DataWarehouseSavedQuery
}): JSX.Element {
    return (
        <>
            {node.type === 'endpoint' ? (
                <Button variant="outline" render={<LinkPrimitive to={nodeEndpointUrl(node)} />}>
                    Open endpoint
                </Button>
            ) : (
                <QuillNodeDetailQueryEditorActions id={id} />
            )}
            <MaterializationRunActions viewId={savedQuery.id} kind={node.type === 'endpoint' ? 'endpoint' : 'view'} />
        </>
    )
}
