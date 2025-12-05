import { useActions, useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { userPreferencesLogic } from 'lib/logic/userPreferencesLogic'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { personLogic } from 'scenes/persons/personLogic'

import { NotebookNodeProps, NotebookNodeType } from '../types'
import { Properties } from './components/Properties'
import { notebookNodeLogic } from './notebookNodeLogic'

const Component = ({ attributes }: NotebookNodeProps<NotebookNodePersonPropertiesAttributes>): JSX.Element | null => {
    const { id, distinctId } = attributes

    const { expanded } = useValues(notebookNodeLogic)

    const logic = personLogic({ id, distinctId })
    const { person, personLoading } = useValues(logic)
    const { pinnedPersonProperties } = useValues(userPreferencesLogic)
    const { pinPersonProperty, unpinPersonProperty } = useActions(userPreferencesLogic)

    if (personLoading) {
        return <LemonSkeleton className="h-6" />
    } else if (!person) {
        return <NotFound object="person" />
    }

    if (!expanded) {
        return null
    }

    const pinnedProperties = Object.fromEntries(
        Object.entries(person.properties).filter(([key, _]) => pinnedPersonProperties.includes(key))
    )
    const unpinnedProperties = Object.fromEntries(
        Object.entries(person.properties).filter(([key, _]) => !pinnedPersonProperties.includes(key))
    )

    return (
        <Properties
            pinnedProperties={pinnedProperties}
            unpinnedProperties={unpinnedProperties}
            onPin={pinPersonProperty}
            onUnpin={unpinPersonProperty}
        />
    )
}

type NotebookNodePersonPropertiesAttributes = {
    id: string
    distinctId: string
}

export const NotebookNodePersonProperties = createPostHogWidgetNode({
    nodeType: NotebookNodeType.PersonProperties,
    titlePlaceholder: 'Properties',
    Component,
    resizeable: false,
    expandable: true,
    startExpanded: true,
    attributes: {
        id: {},
        distinctId: {},
    },
})
