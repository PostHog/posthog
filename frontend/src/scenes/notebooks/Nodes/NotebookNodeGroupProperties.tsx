import { useActions, useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { groupLogic } from 'scenes/groups/groupLogic'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'

import { CustomerProfileScope, PropertyDefinitionType } from '~/types'

import { PinnedPropertiesMenu } from 'products/customer_analytics/frontend/components/PinnedProperties/PinnedPropertiesMenu'
import { pinnedProfilePropertiesLogic } from 'products/customer_analytics/frontend/pinnedProfilePropertiesLogic'

import { NotebookNodeType } from '../types'
import { Properties } from './components/Properties'
import { notebookNodeLogic } from './notebookNodeLogic'

const Component = (): JSX.Element | null => {
    const { expanded } = useValues(notebookNodeLogic)

    const { groupData, groupDataLoading } = useValues(groupLogic)
    const scope = groupProfileScope(groupData?.group_type_index)
    const pinsLogic = pinnedProfilePropertiesLogic({ scope })
    const { pinnedProperties } = useValues(pinsLogic)
    const { pinProperty, unpinProperty } = useActions(pinsLogic)

    if (groupDataLoading) {
        return <LemonSkeleton className="h-6" />
    } else if (!groupData) {
        return <NotFound object="group" />
    }

    if (!expanded) {
        return null
    }

    return (
        <Properties
            key={`${groupData.group_type_index}-${groupData.group_key}`}
            properties={groupData.group_properties || {}}
            pinnedProperties={pinnedProperties}
            onPin={pinProperty}
            onUnpin={unpinProperty}
            type={PropertyDefinitionType.Group}
            actions={<PinnedPropertiesMenu scope={scope} />}
        />
    )
}

// Group pins are shared per group type, matching the profile config the customer profile stores for
// that group type. An unknown index falls back to the first one so the panel still resolves a scope.
function groupProfileScope(groupTypeIndex: number | undefined): CustomerProfileScope {
    const scopes = [
        CustomerProfileScope.GROUP_0,
        CustomerProfileScope.GROUP_1,
        CustomerProfileScope.GROUP_2,
        CustomerProfileScope.GROUP_3,
        CustomerProfileScope.GROUP_4,
    ]
    return scopes[groupTypeIndex ?? 0] ?? CustomerProfileScope.GROUP_0
}

export const NotebookNodeGroupProperties = createPostHogWidgetNode({
    nodeType: NotebookNodeType.GroupProperties,
    titlePlaceholder: 'Properties',
    Component,
    resizeable: false,
    expandable: true,
    startExpanded: true,
    attributes: {},
})
