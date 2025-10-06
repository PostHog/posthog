import { useActions, useValues } from 'kea'

import { IconPin, IconPinFilled } from '@posthog/icons'
import { LemonButton, LemonLabel, LemonSkeleton } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { userPreferencesLogic } from 'lib/logic/userPreferencesLogic'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { personLogic } from 'scenes/persons/personLogic'

import { PropertyDefinitionType } from '~/types'

import { NotebookNodeProps, NotebookNodeType } from '../types'
import { notebookNodeLogic } from './notebookNodeLogic'

const Component = ({ attributes }: NotebookNodeProps<NotebookNodePropertiesAttributes>): JSX.Element | null => {
    const { id, distinctId } = attributes

    const { expanded } = useValues(notebookNodeLogic)

    const logic = personLogic({ id, distinctId })
    const { person, personLoading } = useValues(logic)
    const { pinnedPersonProperties } = useValues(userPreferencesLogic)

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
    const numUnpinnedProperties = Object.keys(unpinnedProperties).length
    const numPinnedProperties = Object.keys(pinnedProperties).length

    return (
        <div className="py-2 px-4 text-xs">
            {Object.entries(pinnedProperties).map(([key, value], index) => {
                const isLast = numUnpinnedProperties === numPinnedProperties && index === numPinnedProperties - 1

                return <PropertyItem key={key} name={key} value={value} isLast={isLast} isPinned />
            })}
            {Object.entries(unpinnedProperties).map(([key, value], index) => {
                const isLast = index === numUnpinnedProperties - 1

                return <PropertyItem key={key} name={key} value={value} isLast={isLast} />
            })}
        </div>
    )
}

function PropertyItem({
    name,
    value,
    isLast,
    isPinned = false,
}: {
    name: string
    value: any
    isLast: boolean
    isPinned?: boolean
}): JSX.Element {
    const { pinPersonProperty, unpinPersonProperty } = useActions(userPreferencesLogic)
    const Icon = isPinned ? IconPinFilled : IconPin
    const onClick = isPinned ? () => unpinPersonProperty(name) : () => pinPersonProperty(name)

    return (
        <div key={name} className="mb-1">
            <LemonLabel className="flex justify-between leading-4">
                <PropertyKeyInfo value={name} />
                <LemonButton noPadding size="small" icon={<Icon />} onClick={onClick} />
            </LemonLabel>
            <div className={`${!isLast && 'border-b border-primary pb-1'}`}>
                <PropertiesTable properties={value} rootKey={name} type={PropertyDefinitionType.Person} />
            </div>
        </div>
    )
}

type NotebookNodePropertiesAttributes = {
    id: string
    distinctId: string
}

export const NotebookNodeProperties = createPostHogWidgetNode({
    nodeType: NotebookNodeType.Properties,
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
