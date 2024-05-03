import { IconBadge, IconBolt, IconCursor, IconEye, IconLeave, IconList, IconLogomark } from '@posthog/icons'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { IconSelectAll } from 'lib/lemon-ui/icons'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { LinkProps } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { CORE_FILTER_DEFINITIONS_BY_GROUP, getCoreFilterDefinition } from 'lib/taxonomy'

import { EventDefinition, PropertyDefinition } from '~/types'

export function getPropertyDefinitionIcon(definition: PropertyDefinition): JSX.Element {
    if (CORE_FILTER_DEFINITIONS_BY_GROUP.event_properties[definition.name]) {
        return (
            <Tooltip title="PostHog event property">
                <IconList className="taxonomy-icon taxonomy-icon-muted" />
            </Tooltip>
        )
    }
    if (definition.verified) {
        return (
            <Tooltip title="Verified event property">
                <IconList className="taxonomy-icon taxonomy-icon-muted" />
            </Tooltip>
        )
    }
    return (
        <Tooltip title="Event property">
            <IconList className="taxonomy-icon taxonomy-icon-muted" />
        </Tooltip>
    )
}

export function getEventDefinitionIcon(definition: EventDefinition & { value?: string | null }): JSX.Element {
    // Rest are events
    if (definition.name === '$pageview' || definition.name === '$screen') {
        return (
            <Tooltip title="Pageview">
                <IconEye className="taxonomy-icon taxonomy-icon-ph taxonomy-icon-muted" />
            </Tooltip>
        )
    }
    if (definition.name === '$pageleave') {
        return (
            <Tooltip title="PostHog event">
                <IconLeave className="taxonomy-icon taxonomy-icon-ph taxonomy-icon-muted" />
            </Tooltip>
        )
    }
    if (definition.name === '$autocapture') {
        return <IconBolt className="taxonomy-icon taxonomy-icon-ph taxonomy-icon-muted" />
    }
    if (definition.name && definition.verified) {
        return (
            <Tooltip title="Custom event">
                <IconCursor className="taxonomy-icon taxonomy-icon-muted" />
            </Tooltip>
        )
    }
    if (definition.name && !!CORE_FILTER_DEFINITIONS_BY_GROUP.events[definition.name]) {
        return (
            <Tooltip title="PostHog event">
                <IconLogomark className="taxonomy-icon taxonomy-icon-muted" />
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
        <Tooltip title="Custom event">
            <IconCursor className="taxonomy-icon taxonomy-icon-muted" />
        </Tooltip>
    )
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
                <>
                    <PropertyKeyInfo
                        value={definition.name ?? ''}
                        disablePopover
                        disableIcon
                        type={taxonomicGroupType}
                    />
                    {definition.verified && (
                        <>
                            <Tooltip
                                title={`${
                                    CORE_FILTER_DEFINITIONS_BY_GROUP.events[definition.name] ? 'PostHog' : 'Verified'
                                } event`}
                            >
                                <IconBadge className=" text-success text-xl" />
                            </Tooltip>
                        </>
                    )}
                    {!!CORE_FILTER_DEFINITIONS_BY_GROUP.events[definition.name] && (
                        <Tooltip title="PostHog event">
                            <IconBadge className="text-success text-xl" />
                        </Tooltip>
                    )}
                </>
            }
        />
    )
}
