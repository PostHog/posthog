import { useActions, useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { personLogic } from 'scenes/persons/personLogic'

import { CustomerProfileScope, PropertyDefinitionType } from '~/types'

import { PinnedPropertiesMenu } from 'products/customer_analytics/frontend/components/PinnedProperties/PinnedPropertiesMenu'
import { pinnedProfilePropertiesLogic } from 'products/customer_analytics/frontend/pinnedProfilePropertiesLogic'

import { NotebookNodeProps, NotebookNodeType } from '../types'
import { Properties } from './components/Properties'
import { notebookNodeLogic } from './notebookNodeLogic'

const Component = ({ attributes }: NotebookNodeProps<NotebookNodePersonPropertiesAttributes>): JSX.Element | null => {
    const { id, distinctId } = attributes

    const { expanded } = useValues(notebookNodeLogic)

    const logic = personLogic({ id, distinctId })
    const { person, personLoading } = useValues(logic)
    const pinsLogic = pinnedProfilePropertiesLogic({ scope: CustomerProfileScope.PERSON })
    const { pinnedProperties } = useValues(pinsLogic)
    const { pinProperty, unpinProperty } = useActions(pinsLogic)

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
            key={id}
            properties={person.properties || {}}
            pinnedProperties={pinnedProperties}
            onPin={pinProperty}
            onUnpin={unpinProperty}
            type={PropertyDefinitionType.Person}
            actions={<PinnedPropertiesMenu scope={CustomerProfileScope.PERSON} />}
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
