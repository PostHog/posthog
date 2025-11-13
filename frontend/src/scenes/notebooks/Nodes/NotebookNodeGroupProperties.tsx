import { useActions, useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { userPreferencesLogic } from 'lib/logic/userPreferencesLogic'
import { groupLogic } from 'scenes/groups/groupLogic'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'

import { NotebookNodeProps, NotebookNodeType } from '../types'
import { Properties } from './components/Properties'
import { notebookNodeLogic } from './notebookNodeLogic'

const Component = ({ attributes }: NotebookNodeProps<NotebookNodeGroupPropertiesAttributes>): JSX.Element | null => {
    const { groupKey, groupTypeIndex } = attributes
    const { expanded } = useValues(notebookNodeLogic)

    const logic = groupLogic({ groupKey, groupTypeIndex })
    const { groupData, groupDataLoading } = useValues(logic)
    const { pinnedGroupProperties } = useValues(userPreferencesLogic)
    const { pinGroupProperty, unpinGroupProperty } = useActions(userPreferencesLogic)

    if (groupDataLoading) {
        return <LemonSkeleton className="h-6" />
    } else if (!groupData) {
        return <NotFound object="group" />
    }

    if (!expanded) {
        return null
    }

    const pinnedProperties = Object.fromEntries(
        Object.entries(groupData.group_properties).filter(([key, _]) => pinnedGroupProperties.includes(key))
    )
    const unpinnedProperties = Object.fromEntries(
        Object.entries(groupData.group_properties).filter(([key, _]) => !pinnedGroupProperties.includes(key))
    )

    return (
        <Properties
            pinnedProperties={pinnedProperties}
            unpinnedProperties={unpinnedProperties}
            onPin={pinGroupProperty}
            onUnpin={unpinGroupProperty}
        />
    )
}

type NotebookNodeGroupPropertiesAttributes = {
    groupKey: string
    groupTypeIndex: number
}

export const NotebookNodeGroupProperties = createPostHogWidgetNode({
    nodeType: NotebookNodeType.GroupProperties,
    titlePlaceholder: 'Properties',
    Component,
    resizeable: false,
    expandable: true,
    startExpanded: true,
    attributes: {
        groupKey: {},
        groupTypeIndex: {},
    },
})
