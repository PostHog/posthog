import { IconFilter } from '@posthog/icons'
import { Button, Collapsible, CollapsibleContent, CollapsibleHeader, CollapsibleTrigger, Text } from '@posthog/quill'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { EventTriggerConfig, TriggerPropertyFilter } from '~/lib/components/IngestionControls/types'

import {
    propertyFiltersToTriggerFilters,
    SUPPORTED_OPERATORS,
    triggerFiltersToPropertyFilters,
} from './triggerGroupHelpers'

export function QuillTriggerGroupEventRow({
    event,
    isExpanded,
    onToggle,
    onRemove,
    onUpdateProperties,
}: {
    event: EventTriggerConfig
    isExpanded: boolean
    onToggle: () => void
    onRemove: () => void
    onUpdateProperties: (properties: TriggerPropertyFilter[]) => void
}): JSX.Element {
    const filterCount = event.properties?.length ?? 0

    return (
        <Collapsible open={isExpanded} onOpenChange={onToggle} className="rounded-md border border-border p-2">
            <CollapsibleHeader className="flex-wrap">
                <CollapsibleTrigger iconOnly>{`Show property filters for ${event.name}`}</CollapsibleTrigger>
                <Text size="xs" weight="medium" render={<span className="min-w-0 flex-1 truncate" />}>
                    {event.name}
                </Text>
                {filterCount > 0 && (
                    <Text size="xs" variant="muted" render={<span className="flex items-center gap-1" />}>
                        <IconFilter />
                        <span>{`${filterCount} filter${filterCount !== 1 ? 's' : ''}`}</span>
                    </Text>
                )}
                <Button variant="destructive-outline" onClick={onRemove}>
                    Remove
                </Button>
            </CollapsibleHeader>
            <CollapsibleContent className="pt-2">
                <div className="flex flex-col gap-2 border-t border-border pt-2">
                    <Text size="xs" weight="medium" render={<p className="m-0" />}>
                        Per-event property filters
                    </Text>
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        Only trigger on this event when these conditions are met.
                    </Text>
                    <PropertyFilters
                        propertyFilters={triggerFiltersToPropertyFilters(event.properties || [])}
                        onChange={(filters) => onUpdateProperties(propertyFiltersToTriggerFilters(filters))}
                        pageKey={`trigger-event-${event.name}`}
                        taxonomicGroupTypes={[
                            TaxonomicFilterGroupType.EventProperties,
                            TaxonomicFilterGroupType.PersonProperties,
                        ]}
                        eventNames={[event.name]}
                        buttonText="Add property filter"
                        buttonSize="small"
                        operatorAllowlist={SUPPORTED_OPERATORS}
                    />
                </div>
            </CollapsibleContent>
        </Collapsible>
    )
}
