import { EventDefinition, PropertyDefinition } from '~/types'
import {
    IconAutocapture,
    IconPageleave,
    IconPreview,
    PropertyIcon,
    IconUnverifiedEvent,
    IconVerifiedEvent,
    VerifiedPropertyIcon,
    IconSelectAll,
} from 'lib/lemon-ui/icons'
import { getKeyMapping, KEY_MAPPING } from 'lib/taxonomy'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { TaxonomicFilterGroup, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import clsx from 'clsx'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'
import {
    eventTaxonomicGroupProps,
    propertyTaxonomicGroupProps,
} from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'

export function getPropertyDefinitionIcon(definition: PropertyDefinition): JSX.Element {
    if (KEY_MAPPING.event[definition.name]) {
        return (
            <Tooltip title="PostHog event property">
                <VerifiedPropertyIcon className="taxonomy-icon taxonomy-icon-verified" />
            </Tooltip>
        )
    }
    if (definition.verified) {
        return (
            <Tooltip title="Verified event property">
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

export function getEventDefinitionIcon(definition: EventDefinition & { value: string | null }): JSX.Element {
    // Rest are events
    if (definition.name === '$pageview' || definition.name === '$screen') {
        return (
            <Tooltip title="PostHog event">
                <IconPreview className="taxonomy-icon taxonomy-icon-ph taxonomy-icon-verified" />
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
    if (definition.name && (definition.verified || !!KEY_MAPPING.event[definition.name])) {
        return (
            <Tooltip title={`${KEY_MAPPING.event[definition.name] ? 'PostHog' : 'Verified'} event`}>
                <IconVerifiedEvent className="taxonomy-icon taxonomy-icon-verified" />
            </Tooltip>
        )
    }
    if (definition.value === null) {
        return (
            <Tooltip title="All events">
                <IconSelectAll className="taxonomy-icon taxonomy-icon-built-in" />
            </Tooltip>
        )
    }
    return (
        <Tooltip title={`Unverified event`}>
            <IconUnverifiedEvent className="taxonomy-icon taxonomy-icon-muted" />
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
        <span className={clsx('definition-column-name-content-title', asLink && 'text-link cursor-pointer')}>
            <PropertyKeyInfo value={definition.name ?? ''} disablePopover disableIcon />
        </span>
    )
    const linkedInnerContent = isLink ? (
        <Link to={fullDetailUrl} preventClick={!fullDetailUrl}>
            {innerContent}
        </Link>
    ) : (
        innerContent
    )

    const description = definition.description || getKeyMapping(definition.name, 'event')?.description

    return (
        <>
            {!hideIcon && icon && <div className="definition-column-name-icon">{icon}</div>}
            {!hideText && (
                <div className="definition-column-name-content">
                    <div>{linkedInnerContent}</div>
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
