import { IconBadge, IconBolt, IconCursor, IconEye, IconLeave, IconList, IconLogomark } from '@posthog/icons'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import {
    eventTaxonomicGroupProps,
    propertyTaxonomicGroupProps,
} from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { TaxonomicFilterGroup, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { IconSelectAll } from 'lib/lemon-ui/icons'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { CORE_FILTER_DEFINITIONS_BY_GROUP, getCoreFilterDefinition } from 'lib/taxonomy'
import { urls } from 'scenes/urls'

import { EventDefinition, PropertyDefinition } from '~/types'

export function getPropertyDefinitionIcon(definition: PropertyDefinition): JSX.Element {
    if (CORE_FILTER_DEFINITIONS_BY_GROUP.event_properties[definition.name]) {
        return (
            <Tooltip title="PostHog event property">
                <span>
                    <IconList className="taxonomy-icon taxonomy-icon-muted" />
                </span>
            </Tooltip>
        )
    }
    if (definition.verified) {
        return (
            <Tooltip title="Verified event property">
                <span>
                    <IconList className="taxonomy-icon taxonomy-icon-muted" />
                </span>
            </Tooltip>
        )
    }
    return (
        <Tooltip title="Event property">
            <span>
                <IconList className="taxonomy-icon taxonomy-icon-muted" />
            </span>
        </Tooltip>
    )
}

export function getEventDefinitionIcon(definition: EventDefinition & { value: string | null }): JSX.Element {
    // Rest are events
    if (definition.name === '$pageview' || definition.name === '$screen') {
        return (
            <Tooltip title="Pageview">
                <span>
                    <IconEye className="taxonomy-icon taxonomy-icon-ph taxonomy-icon-muted" />
                </span>
            </Tooltip>
        )
    }
    if (definition.name === '$pageleave') {
        return (
            <Tooltip title="PostHog event">
                <span>
                    <IconLeave className="taxonomy-icon taxonomy-icon-ph taxonomy-icon-muted" />
                </span>
            </Tooltip>
        )
    }
    if (definition.name === '$autocapture') {
        return <IconBolt className="taxonomy-icon taxonomy-icon-ph taxonomy-icon-muted" />
    }
    if (definition.name && definition.verified) {
        return (
            <Tooltip title="Custom event">
                <span>
                    <IconCursor className="taxonomy-icon taxonomy-icon-muted" />
                </span>
            </Tooltip>
        )
    }
    if (definition.name && !!CORE_FILTER_DEFINITIONS_BY_GROUP.events[definition.name]) {
        return (
            <Tooltip title="PostHog event">
                <span>
                    <IconLogomark className="taxonomy-icon taxonomy-icon-muted" />
                </span>
            </Tooltip>
        )
    }
    if (definition.value === null) {
        return (
            <Tooltip title="All events">
                <span>
                    <IconSelectAll className="taxonomy-icon taxonomy-icon-built-in" />
                </span>
            </Tooltip>
        )
    }
    return (
        <Tooltip title="Custom event">
            <span>
                <IconCursor className="taxonomy-icon taxonomy-icon-muted" />
            </span>
        </Tooltip>
    )
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
    definition: EventDefinition | PropertyDefinition
    group: TaxonomicFilterGroup
} & SharedDefinitionHeaderProps): JSX.Element {
    const fullDetailUrl = group.getFullDetailUrl?.(definition)
    const icon = group.getIcon?.(definition)
    const isLink = asLink && fullDetailUrl

    const innerContent = (
        <span className={asLink ? 'text-link cursor-pointer' : ''}>
            <PropertyKeyInfo value={definition.name ?? ''} disablePopover disableIcon type={group.type} />
        </span>
    )
    const linkedInnerContent = isLink ? (
        <Link to={fullDetailUrl} preventClick={!fullDetailUrl}>
            {innerContent}
        </Link>
    ) : (
        innerContent
    )

    const description = definition.description || getCoreFilterDefinition(definition.name, group.type)?.description

    return (
        <>
            {!hideIcon && icon && <div className="definition-column-name-icon">{icon}</div>}
            {!hideText && (
                <div className="definition-column-name-content">
                    <div className="definition-column-name-content-title">
                        {linkedInnerContent}
                        {definition.verified && (
                            <>
                                <Tooltip
                                    title={`${
                                        CORE_FILTER_DEFINITIONS_BY_GROUP.events[definition.name]
                                            ? 'PostHog'
                                            : 'Verified'
                                    } event`}
                                >
                                    <span>
                                        <IconBadge
                                            className="w-5 h-5 taxonomy-icon taxonomy-icon-muted"
                                            style={{ width: '1.25rem' }}
                                        />
                                    </span>
                                </Tooltip>
                            </>
                        )}
                        {!!CORE_FILTER_DEFINITIONS_BY_GROUP.events[definition.name] && (
                            <Tooltip title="PostHog event">
                                <span>
                                    <IconBadge
                                        className="w-5 h-5 taxonomy-icon taxonomy-icon-muted"
                                        style={{ width: '1.25rem' }}
                                    />
                                </span>
                            </Tooltip>
                        )}
                    </div>
                    {description ? <div className="text-xs text-ellipsis">{description}</div> : null}
                </div>
            )}
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
                    urls.propertyDefinition(propertyDefinition.id),
                ...propertyTaxonomicGroupProps(),
            }}
            {...props}
        />
    )
}
