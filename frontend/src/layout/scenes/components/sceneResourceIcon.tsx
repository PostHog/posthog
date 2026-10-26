import { FileSystemIconType } from '~/queries/schema/schema-general'

import { ProductIconWrapper, iconForType } from '../../panel-layout/ProjectTree/defaultTree'
import type { ResourceType } from './SceneTitleSection'

export function sceneResourceIcon(resourceType: ResourceType): JSX.Element {
    return resourceType.forceIcon ? (
        <ProductIconWrapper type={resourceType.type} colorOverride={resourceType.forceIconColorOverride}>
            {resourceType.forceIcon}
        </ProductIconWrapper>
    ) : (
        iconForType(resourceType.type ? (resourceType.type as FileSystemIconType) : undefined)
    )
}
