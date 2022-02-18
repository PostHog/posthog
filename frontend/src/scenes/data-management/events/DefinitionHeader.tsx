import React from 'react'
import { EventDefinition, PropertyDefinition } from '~/types'
import {
    AutocaptureIcon,
    PageleaveIcon,
    PageviewIcon,
    PropertyIcon,
    UnverifiedEventStack,
    VerifiedEventStack,
} from 'lib/components/icons'
import { keyMapping, PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { Tooltip } from 'lib/components/Tooltip'

export enum DefinitionType {
    Event = 'event',
    Property = 'property',
}

export function getDefinitionIcon(
    definition: EventDefinition | PropertyDefinition,
    type: DefinitionType = DefinitionType.Event
): JSX.Element {
    if (type === DefinitionType.Property) {
        return <PropertyIcon className="taxonomy-icon taxonomy-icon-muted" />
    }
    const _definition = definition as EventDefinition
    // Rest are events
    if (_definition.name === '$pageview') {
        return (
            <Tooltip title="Verified event">
                <PageviewIcon className="taxonomy-icon taxonomy-icon-verified" />
            </Tooltip>
        )
    }
    if (_definition.name === '$pageleave') {
        return (
            <Tooltip title="Verified event">
                <PageleaveIcon className="taxonomy-icon taxonomy-icon-verified" />
            </Tooltip>
        )
    }
    if (_definition.name === '$autocapture') {
        return (
            <Tooltip title="Verified event">
                <AutocaptureIcon className="taxonomy-icon taxonomy-icon-verified" />
            </Tooltip>
        )
    }
    if (_definition.verified || !!keyMapping.event[_definition.name]) {
        return (
            <Tooltip title="Verified event">
                <VerifiedEventStack className="taxonomy-icon taxonomy-icon-verified" />
            </Tooltip>
        )
    }
    return <UnverifiedEventStack className="taxonomy-icon taxonomy-icon-muted" />
}

export function DefinitionHeader({
    definition,
    hideIcon = false,
}: {
    definition: EventDefinition | PropertyDefinition
    hideIcon?: boolean
}): JSX.Element {
    return (
        <>
            {!hideIcon && <div className="definition-column-name-icon">{getDefinitionIcon(definition)}</div>}
            <div className="definition-column-name-content">
                <div className="definition-column-name-content-title">
                    <PropertyKeyInfo value={definition.name ?? ''} disablePopover disableIcon />
                </div>
                <div className="definition-column-name-content-description">
                    {definition.description || 'There is no description for this event'}
                </div>
            </div>
        </>
    )
}
