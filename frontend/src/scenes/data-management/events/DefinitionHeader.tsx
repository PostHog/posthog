import React, { useState } from 'react'
import { EventDefinition, PropertyDefinition } from '~/types'
import {
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
import { DefinitionPopupContents } from 'lib/components/DefinitionPopup/DefinitionPopupContents'
import {
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
} from 'lib/components/TaxonomicFilter/types'
import { useActions, useValues } from 'kea'
import {
    createDefinitionKey,
    eventDefinitionsTableLogic,
} from 'scenes/data-management/events/eventDefinitionsTableLogic'
import { getSingularType } from 'lib/components/DefinitionPopup/utils'
import clsx from 'clsx'
import { Link } from 'lib/components/Link'
import { urls } from 'scenes/urls'

export enum DefinitionType {
    Event = 'event',
    Property = 'property',
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

export function getEventDefinitionIcon(definition: EventDefinition): JSX.Element {
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
    hideView?: boolean
    hideEdit?: boolean
    asLink?: boolean
    openDetailInNewTab?: boolean
    updateRemoteItem?: (definition: TaxonomicDefinitionTypes) => void
}

function RawDefinitionHeader({
    definition,
    definitionKey,
    group,
    updateRemoteItem,
    hideIcon = false,
    hideView = false,
    hideEdit = false,
    asLink = false,
    openDetailInNewTab = true,
}: {
    definition: EventDefinition | PropertyDefinition
    definitionKey: string
    group: TaxonomicFilterGroup
} & SharedDefinitionHeaderProps): JSX.Element {
    const [referenceEl, setReferenceEl] = useState<HTMLSpanElement | null>(null)
    const { hoveredDefinition } = useValues(eventDefinitionsTableLogic)
    const { setHoveredDefinition } = useActions(eventDefinitionsTableLogic)

    const fullDetailUrl = group.getFullDetailUrl?.(definition)
    const icon = group.getIcon?.(definition)
    const isLink = asLink && fullDetailUrl

    const innerContent = (
        <span
            ref={setReferenceEl}
            onMouseOver={() => {
                setHoveredDefinition(definitionKey)
            }}
            onMouseOut={() => {
                setHoveredDefinition(null)
            }}
        >
            <PropertyKeyInfo
                value={definition.name ?? ''}
                disablePopover
                disableIcon
                className={clsx('definition-column-name-content-title', asLink && 'text-primary')}
                style={{
                    cursor: isLink ? 'pointer' : 'text',
                }}
            />
        </span>
    )
    const linkedInnerContent = isLink ? (
        <Link target={openDetailInNewTab ? '_blank' : undefined} to={fullDetailUrl} preventClick={!fullDetailUrl}>
            {innerContent}
        </Link>
    ) : (
        innerContent
    )

    return (
        <>
            {!hideIcon && icon && <div className="definition-column-name-icon">{icon}</div>}
            <div className="definition-column-name-content">
                <div>
                    {hoveredDefinition !== definitionKey ? (
                        linkedInnerContent
                    ) : (
                        <DefinitionPopupContents
                            item={definition}
                            group={group}
                            referenceEl={referenceEl}
                            onMouseLeave={() => {
                                setHoveredDefinition(null)
                            }}
                            onCancel={() => {
                                setHoveredDefinition(null)
                            }}
                            updateRemoteItem={updateRemoteItem}
                            hideView={hideView}
                            hideEdit={hideEdit}
                        >
                            {linkedInnerContent}
                        </DefinitionPopupContents>
                    )}
                </div>
                <div className="definition-column-name-content-description">
                    {definition.description || `There is no description for this ${getSingularType(group.type)}`}
                </div>
            </div>
        </>
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
            definitionKey={createDefinitionKey(definition)}
            group={{
                name: 'Events',
                searchPlaceholder: 'events',
                type: TaxonomicFilterGroupType.Events,
                getName: (eventDefinition: EventDefinition) => eventDefinition.name,
                getValue: (eventDefinition: EventDefinition) => eventDefinition.name,
                getPopupHeader: (eventDefinition: EventDefinition): string => {
                    if (!!keyMapping.event[eventDefinition.name]) {
                        return 'Default Event'
                    }
                    return `${eventDefinition.verified ? 'Verified' : 'Unverified'} Event`
                },
                getIcon: getEventDefinitionIcon,
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
            definitionKey={createDefinitionKey(event, definition)}
            group={{
                name: 'Event properties',
                searchPlaceholder: 'event properties',
                type: TaxonomicFilterGroupType.EventProperties,
                getName: (propertyDefinition: PropertyDefinition) => propertyDefinition.name,
                getValue: (propertyDefinition: PropertyDefinition) => propertyDefinition.name,
                getPopupHeader: () => 'Property',
                getIcon: getPropertyDefinitionIcon,
                getFullDetailUrl: (propertyDefinition: PropertyDefinition) =>
                    urls.eventPropertyStat(propertyDefinition.id),
            }}
            {...props}
        />
    )
}
