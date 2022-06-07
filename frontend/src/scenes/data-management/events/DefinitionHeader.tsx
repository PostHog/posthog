import React from 'react'
import { ActionType, CombinedEvent, EventDefinition, PropertyDefinition } from '~/types'
import {
    ActionStack,
    AutocaptureIcon,
    PageleaveIcon,
    PageviewIcon,
    PropertyIcon,
    UnverifiedEventStack,
    VerifiedEventStack,
    VerifiedPropertyIcon,
} from 'lib/components/icons'
import { keyMapping, PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { Tooltip } from 'lib/components/Tooltip'
import { TaxonomicFilterGroup, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { getSingularType } from 'lib/components/DefinitionPopup/utils'
import clsx from 'clsx'
import { Link } from 'lib/components/Link'
import { urls } from 'scenes/urls'
import {
    eventTaxonomicGroupProps,
    propertyTaxonomicGroupProps,
} from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { isActionEvent } from 'scenes/data-management/events/eventDefinitionsTableLogic'
import { actionsModel } from '~/models/actionsModel'

export enum DefinitionType {
    Event = 'event',
    Property = 'property',
    Action = 'action',
}

export function getPropertyDefinitionIcon(definition: PropertyDefinition): JSX.Element {
    if (!!keyMapping.event[definition.name]) {
        return (
            <Tooltip title="Verified PostHog event property">
                <VerifiedPropertyIcon className="taxonomy-icon taxonomy-icon-verified" />
            </Tooltip>
        )
    }
    return <PropertyIcon className="taxonomy-icon taxonomy-icon-muted" />
}

export function getEventDefinitionOrActionIcon(definition: CombinedEvent): JSX.Element {
    if (isActionEvent(definition)) {
        if (definition.verified) {
            return (
                <Tooltip title="Verified event filter">
                    <ActionStack className="taxonomy-icon taxonomy-icon-verified" />
                </Tooltip>
            )
        }
        return <ActionStack className="taxonomy-icon taxonomy-icon-muted" />
    }
    // Rest are events
    if (definition.name === '$pageview') {
        return (
            <Tooltip title="Verified PostHog event">
                <PageviewIcon className="taxonomy-icon taxonomy-icon-ph taxonomy-icon-verified" />
            </Tooltip>
        )
    }
    if (definition.name === '$pageleave') {
        return (
            <Tooltip title="Verified PostHog event">
                <PageleaveIcon className="taxonomy-icon taxonomy-icon-ph taxonomy-icon-verified" />
            </Tooltip>
        )
    }
    if (definition.name === '$autocapture') {
        return (
            <Tooltip title="Verified PostHog event">
                <AutocaptureIcon className="taxonomy-icon taxonomy-icon-ph taxonomy-icon-verified" />
            </Tooltip>
        )
    }
    if (definition.verified || !!keyMapping.event[definition.name]) {
        return (
            <Tooltip title={`Verified${!!keyMapping.event[definition.name] ? ' PostHog' : ' event'}`}>
                <VerifiedEventStack className="taxonomy-icon taxonomy-icon-verified" />
            </Tooltip>
        )
    }
    return <UnverifiedEventStack className="taxonomy-icon taxonomy-icon-muted" />
}

interface SharedDefinitionHeaderProps {
    hideIcon?: boolean
    hideText?: boolean
    asLink?: boolean
}

function RawDefinitionHeader({
    definition,
    group,
    hideIcon = false,
    hideText = false,
    asLink = false,
}: {
    definition: CombinedEvent | PropertyDefinition
    group: TaxonomicFilterGroup
} & SharedDefinitionHeaderProps): JSX.Element {
    const fullDetailUrl = group.getFullDetailUrl?.(definition)
    const icon = group.getIcon?.(definition)
    const isLink = asLink && fullDetailUrl

    const innerContent = (
        <PropertyKeyInfo
            value={definition.name ?? ''}
            disablePopover
            disableIcon
            className={clsx('definition-column-name-content-title', asLink && 'text-primary')}
            style={{
                cursor: isLink ? 'pointer' : 'text',
            }}
        />
    )
    const linkedInnerContent = isLink ? (
        <Link to={fullDetailUrl} preventClick={!fullDetailUrl}>
            {innerContent}
        </Link>
    ) : (
        innerContent
    )

    return (
        <>
            {!hideIcon && icon && <div className="definition-column-name-icon">{icon}</div>}
            {!hideText && (
                <div className="definition-column-name-content">
                    <div>{linkedInnerContent}</div>
                    <div className="definition-column-name-content-description">
                        {definition.description || <i>Add a description for this {getSingularType(group.type)}</i>}
                    </div>
                </div>
            )}
        </>
    )
}

export function ActionHeader({
    definition,
    ...props
}: { definition: ActionType } & SharedDefinitionHeaderProps): JSX.Element {
    return (
        <RawDefinitionHeader
            definition={definition}
            group={{
                name: 'Event filters',
                searchPlaceholder: 'actions',
                type: TaxonomicFilterGroupType.Actions,
                logic: actionsModel,
                value: 'actions',
                getName: (action: ActionType) => action.name || '',
                getValue: (action: ActionType) => action.name || '',
                getFullDetailUrl: (action: ActionType) => urls.action(action.id),
                getPopupHeader: () => 'Event filter',
                getIcon: function _getIcon(): JSX.Element {
                    return <ActionStack className="taxonomy-icon taxonomy-icon-muted" />
                },
            }}
            {...props}
        />
    )
}

export function EventDefinitionHeader({
    definition,
    ...props
}: {
    definition: EventDefinition
} & SharedDefinitionHeaderProps): JSX.Element {
    return (
        <RawDefinitionHeader
            definition={definition}
            group={{
                name: 'Events',
                searchPlaceholder: 'events',
                type: TaxonomicFilterGroupType.Events,
                getName: (eventDefinition: EventDefinition) => eventDefinition.name,
                getValue: (eventDefinition: EventDefinition) => eventDefinition.name,
                getFullDetailUrl: (eventDefinition: EventDefinition) => urls.eventDefinition(eventDefinition.id),
                ...eventTaxonomicGroupProps,
            }}
            {...props}
        />
    )
}

export function PropertyDefinitionHeader({
    definition,
    event,
    ...props
}: {
    definition: PropertyDefinition
    event?: EventDefinition
} & SharedDefinitionHeaderProps): JSX.Element {
    return (
        <RawDefinitionHeader
            definition={definition}
            group={{
                name: 'Event properties',
                searchPlaceholder: 'event properties',
                type: TaxonomicFilterGroupType.EventProperties,
                getName: (propertyDefinition: PropertyDefinition) => propertyDefinition.name,
                getValue: (propertyDefinition: PropertyDefinition) => propertyDefinition.name,
                getFullDetailUrl: (propertyDefinition: PropertyDefinition) =>
                    urls.eventPropertyDefinition(propertyDefinition.id),
                ...propertyTaxonomicGroupProps(),
            }}
            {...props}
        />
    )
}
