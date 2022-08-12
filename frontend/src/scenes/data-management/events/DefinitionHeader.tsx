import React from 'react'
import { ActionType, CombinedEvent, EventDefinition, PropertyDefinition } from '~/types'
import {
    ActionEvent,
    IconAutocapture,
    IconPageleave,
    IconPageview,
    PropertyIcon,
    UnverifiedEvent,
    VerifiedEvent,
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
import { actionsModel } from '~/models/actionsModel'
import { isActionEvent } from 'scenes/data-management/events/eventDefinitionsTableLogic'

export function getPropertyDefinitionIcon(definition: PropertyDefinition): JSX.Element {
    if (!!keyMapping.event[definition.name]) {
        return (
            <Tooltip title="PostHog event property">
                <VerifiedPropertyIcon className="taxonomy-icon taxonomy-icon-verified" />
            </Tooltip>
        )
    }
    return (
        <Tooltip title="Event property">
            <PropertyIcon className="taxonomy-icon taxonomy-icon-muted" />
        </Tooltip>
    )
}

export function getEventDefinitionIcon(definition: CombinedEvent): JSX.Element {
    if (isActionEvent(definition)) {
        return (
            <Tooltip title="Calculated event">
                <ActionEvent className="taxonomy-icon taxonomy-icon-muted" />
            </Tooltip>
        )
    }
    // Rest are events
    if (definition.name === '$pageview') {
        return (
            <Tooltip title="PostHog event">
                <IconPageview className="taxonomy-icon taxonomy-icon-ph taxonomy-icon-verified" />
            </Tooltip>
        )
    }
    if (definition.name === '$pageleave') {
        return (
            <Tooltip title="PostHog event">
                <IconPageleave className="taxonomy-icon taxonomy-icon-ph taxonomy-icon-verified" />
            </Tooltip>
        )
    }
    if (definition.name === '$autocapture') {
        return (
            <Tooltip title="PostHog event">
                <IconAutocapture className="taxonomy-icon taxonomy-icon-ph taxonomy-icon-verified" />
            </Tooltip>
        )
    }
    if (definition.name && (definition.verified || !!keyMapping.event[definition.name])) {
        return (
            <Tooltip title={`${!!keyMapping.event[definition.name] ? 'PostHog' : 'Verified'} event`}>
                <VerifiedEvent className="taxonomy-icon taxonomy-icon-verified" />
            </Tooltip>
        )
    }
    return (
        <Tooltip title={`Unverified event`}>
            <UnverifiedEvent className="taxonomy-icon taxonomy-icon-muted" />
        </Tooltip>
    )
}

interface SharedDefinitionHeaderProps {
    hideIcon?: boolean
    hideText?: boolean
    asLink?: boolean
    shouldSimplifyActions?: boolean
}

function RawDefinitionHeader({
    definition,
    group,
    hideIcon = false,
    hideText = false,
    asLink = false,
    shouldSimplifyActions = false,
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
                        {definition.description || (
                            <i>Add a description for this {getSingularType(group.type, shouldSimplifyActions)}</i>
                        )}
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
                name: 'Calculated events',
                searchPlaceholder: 'calculated events',
                type: TaxonomicFilterGroupType.Actions,
                logic: actionsModel,
                value: 'actions',
                getName: (action: ActionType) => action.name || '',
                getValue: (action: ActionType) => action.name || '',
                getFullDetailUrl: (action: ActionType) => (action.action_id ? urls.action(action.action_id) : ''),
                getPopupHeader: () => 'calculated event',
                getIcon: getEventDefinitionIcon,
            }}
            shouldSimplifyActions
            {...props}
        />
    )
}

export function EventDefinitionHeader({
    definition,
    shouldSimplifyActions = false,
    ...props
}: {
    definition: EventDefinition
    shouldSimplifyActions?: boolean
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
            shouldSimplifyActions={shouldSimplifyActions}
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
