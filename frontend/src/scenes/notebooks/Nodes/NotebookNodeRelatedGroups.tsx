import { useValues } from 'kea'

import { RelatedGroups, RelatedGroupsProps } from 'scenes/groups/RelatedGroups'
import { urls } from 'scenes/urls'

import { NotebookNodeProps, NotebookNodeType } from '../types'
import { createPostHogWidgetNode } from './NodeWrapper'
import { notebookNodeLogic } from './notebookNodeLogic'

const Component = ({ attributes }: NotebookNodeProps<NotebookNodeRelatedGroupsAttributes>): JSX.Element | null => {
    const { expanded } = useValues(notebookNodeLogic)

    if (!expanded) {
        return null
    }

    return <RelatedGroups {...attributes} pageSize={10} embedded />
}

type NotebookNodeRelatedGroupsAttributes = Pick<RelatedGroupsProps, 'id' | 'groupTypeIndex' | 'type'>

const href = ({ id, groupTypeIndex }: NotebookNodeRelatedGroupsAttributes): string => {
    if (typeof groupTypeIndex === 'number') {
        return urls.group(groupTypeIndex, id, false, 'related')
    }
    return urls.personByUUID(id) + '#activeTab=related'
}

export const NotebookNodeRelatedGroups = createPostHogWidgetNode<NotebookNodeRelatedGroupsAttributes>({
    nodeType: NotebookNodeType.RelatedGroups,
    titlePlaceholder: 'Related groups',
    Component,
    resizeable: false,
    expandable: true,
    startExpanded: true,
    href,
    attributes: {
        id: {},
        groupTypeIndex: {},
        type: {},
    },
})
