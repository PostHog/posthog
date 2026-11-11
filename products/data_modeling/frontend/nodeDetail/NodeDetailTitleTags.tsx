import { LemonTag } from '@posthog/lemon-ui'

import { DataModelingNode, DataModelingNodeType } from '~/types'

import { WarehouseColumnAnnotationDescriptionSourceEnumApi } from '../generated/api.schemas'
import { NODE_TYPE_TAG_SETTINGS } from '../lineage/nodeStyles'

export function NodeDetailTitleTags({
    nodeType,
    node,
}: {
    nodeType: DataModelingNodeType | undefined
    node: DataModelingNode | null
}): JSX.Element {
    const typeTag = nodeType ? NODE_TYPE_TAG_SETTINGS[nodeType] : null
    const aiWritten =
        !!node?.description && node.description_source === WarehouseColumnAnnotationDescriptionSourceEnumApi.AiGenerated
    return (
        <div className="flex items-center gap-1">
            {typeTag && <LemonTag type={typeTag.type}>{typeTag.label}</LemonTag>}
            {aiWritten && <LemonTag type="muted">AI-written description</LemonTag>}
        </div>
    )
}
