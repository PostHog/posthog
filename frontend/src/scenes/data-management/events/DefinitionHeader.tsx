import React from 'react'

import { IconBadge, IconBolt, IconCursor, IconEye, IconLeave, IconList, IconLogomark } from '@posthog/icons'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { LinkProps } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconEyeHidden, IconSelectAll } from 'lib/lemon-ui/icons'

import { getCoreFilterDefinition } from '~/taxonomy/helpers'
import { CORE_FILTER_DEFINITIONS_BY_GROUP } from '~/taxonomy/taxonomy'
import { EventDefinition, PropertyDefinition } from '~/types'

interface IconWithBadgeProps {
    icon: JSX.Element
    verified?: boolean
    hidden?: boolean
    tooltipTitle: string
    className?: string
}

function IconWithBadge({ icon, verified, hidden, tooltipTitle, className }: IconWithBadgeProps): JSX.Element {
    const wrappedIcon = (
        <div className="relative inline-flex">
            {React.cloneElement(icon, { className: className || icon.props.className })}
            {(verified || hidden) && (
                <div className="absolute -bottom-1 -left-2 flex items-center justify-center rounded-full bg-primary-light shadow-md p-[1px]">
                    {hidden ? (
                        <IconEyeHidden className="text-danger text-xs" />
                    ) : (
                        <IconBadge className="text-success text-xs" />
                    )}
                </div>
            )}
        </div>
    )

    const tooltipSuffix = hidden ? ', hidden' : verified ? ', verified' : ''
    return <Tooltip title={`${tooltipTitle}${tooltipSuffix}`}>{wrappedIcon}</Tooltip>
}

export function getPropertyDefinitionIcon(definition: PropertyDefinition): JSX.Element {
    if (CORE_FILTER_DEFINITIONS_BY_GROUP.event_properties[definition.name]) {
        return (
            <IconWithBadge
                icon={<IconLogomark />}
                tooltipTitle="PostHog event property"
                className="taxonomy-icon taxonomy-icon-muted"
                verified={definition.verified}
                hidden={definition.hidden}
            />
        )
    }
    return (
        <IconWithBadge
            icon={<IconList />}
            tooltipTitle="Event property"
            className="taxonomy-icon taxonomy-icon-muted"
            verified={definition.verified}
            hidden={definition.hidden}
        />
    )
}

export function getEventDefinitionIcon(definition: EventDefinition & { value?: string | null }): JSX.Element {
    // Rest are events
    if (definition.name === '$pageview' || definition.name === '$screen') {
        return (
            <IconWithBadge
                icon={<IconEye />}
                verified={definition.verified}
                hidden={definition.hidden}
                tooltipTitle="Pageview"
                className="taxonomy-icon taxonomy-icon-ph taxonomy-icon-muted"
            />
        )
    }
    if (definition.name === '$pageleave') {
        return (
            <IconWithBadge
                icon={<IconLeave />}
                verified={definition.verified}
                hidden={definition.hidden}
                tooltipTitle="PostHog event"
                className="taxonomy-icon taxonomy-icon-ph taxonomy-icon-muted"
            />
        )
    }
    if (definition.name === '$autocapture') {
        return (
            <IconWithBadge
                icon={<IconBolt />}
                verified={definition.verified}
                hidden={definition.hidden}
                tooltipTitle="Autocapture event"
                className="taxonomy-icon taxonomy-icon-ph taxonomy-icon-muted"
            />
        )
    }
    if (definition.name && !!CORE_FILTER_DEFINITIONS_BY_GROUP.events[definition.name]) {
        return (
            <IconWithBadge
                icon={<IconLogomark />}
                verified={definition.verified}
                hidden={definition.hidden}
                tooltipTitle="PostHog event"
                className="taxonomy-icon taxonomy-icon-muted"
            />
        )
    }
    if (definition.value === null) {
        return (
            <IconWithBadge
                icon={<IconSelectAll />}
                verified={definition.verified}
                hidden={definition.hidden}
                tooltipTitle="All events"
                className="taxonomy-icon taxonomy-icon-built-in"
            />
        )
    }
    return (
        <IconWithBadge
            icon={<IconCursor />}
            verified={definition.verified}
            hidden={definition.hidden}
            tooltipTitle="Custom event"
            className="taxonomy-icon taxonomy-icon-muted"
        />
    )
}

export function getEventMetadataDefinitionIcon(definition: PropertyDefinition): JSX.Element {
    if (CORE_FILTER_DEFINITIONS_BY_GROUP.event_metadata[definition.id]) {
        return <IconLogomark />
    }
    return <IconList />
}

export function getRevenueAnalyticsDefinitionIcon(definition: PropertyDefinition): JSX.Element {
    if (CORE_FILTER_DEFINITIONS_BY_GROUP.revenue_analytics_properties[definition.id]) {
        return <IconLogomark />
    }

    return <IconList />
}

export function DefinitionHeader({
    to,
    definition,
    taxonomicGroupType,
}: {
    to: LinkProps['to']
    definition: EventDefinition | PropertyDefinition
    taxonomicGroupType: TaxonomicFilterGroupType
}): JSX.Element {
    const description =
        definition.description || getCoreFilterDefinition(definition.name, taxonomicGroupType)?.description

    return (
        <LemonTableLink
            to={to}
            description={description}
            title={
                <PropertyKeyInfo value={definition.name ?? ''} disablePopover disableIcon type={taxonomicGroupType} />
            }
        />
    )
}
