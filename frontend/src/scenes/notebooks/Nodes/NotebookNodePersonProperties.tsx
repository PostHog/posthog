import { useActions, useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { userPreferencesLogic } from 'lib/logic/userPreferencesLogic'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { personLogic } from 'scenes/persons/personLogic'

import { PropertyDefinitionType } from '~/types'

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

    return (
        <Properties
            properties={person.properties || {}}
            pinnedProperties={pinnedPersonProperties}
            onPin={pinPersonProperty}
            onUnpin={unpinPersonProperty}
            type={PropertyDefinitionType.Person}
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
