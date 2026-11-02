import { useActions, useValues } from 'kea'

import { IconBolt, IconX } from '@posthog/icons'
import {
    Button,
    ButtonGroup,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { EntityTypes, FilterLogicalOperator } from '~/types'

import { FilterBarChipLabel } from './FilterBarChipLabel'
import { FilterBarChipMenu } from './FilterBarChipMenu'
import { fieldLabelForKey } from './filterBarFields'
import { FilterBarFieldSegment } from './FilterBarFieldSegment'
import { filterBarLogic } from './filterBarLogic'
import { FilterBarEventNode } from './filterBarTypes'

const PERFORMED = 'performed'
const NOT_PERFORMED = 'not_performed'

/** "Pageview performed", laid out like a filter chip: the field, then its operator. The property filters that narrow the event show under it in the stacked editor. */
export function FilterBarEventChip({
    node,
    wrapType,
}: {
    node: FilterBarEventNode
    wrapType?: FilterLogicalOperator | null
}): JSX.Element {
    const { categoriesById } = useValues(filterBarLogic)
    const { setEventNegation, removeItem, replaceEventField } = useActions(filterBarLogic)
    const { event } = node
    const rawName = event.name ?? String(event.id)
    const name = event.type === EntityTypes.EVENTS ? fieldLabelForKey('events', rawName) : rawName

    const label = (
        <>
            <IconBolt className="shrink-0" />
            <span className="truncate">{name}</span>
        </>
    )

    return (
        <ButtonGroup className="max-w-full" data-attr="filter-bar-event">
            {categoriesById.events && event.type === EntityTypes.EVENTS ? (
                <FilterBarFieldSegment purpose="replace-event" onPick={(picked) => replaceEventField(node.id, picked)}>
                    {label}
                </FilterBarFieldSegment>
            ) : (
                <FilterBarChipLabel>{label}</FilterBarChipLabel>
            )}
            <DropdownMenu modal={false}>
                <DropdownMenuTrigger render={<Button variant="outline" />} data-attr="filter-bar-event-negation">
                    {event.negation ? 'not performed' : 'performed'}
                </DropdownMenuTrigger>
                <DropdownMenuContent>
                    <DropdownMenuRadioGroup
                        value={event.negation ? NOT_PERFORMED : PERFORMED}
                        onValueChange={(value) => setEventNegation(node.id, value === NOT_PERFORMED)}
                    >
                        <DropdownMenuRadioItem value={PERFORMED}>performed</DropdownMenuRadioItem>
                        <DropdownMenuRadioItem value={NOT_PERFORMED}>not performed</DropdownMenuRadioItem>
                    </DropdownMenuRadioGroup>
                </DropdownMenuContent>
            </DropdownMenu>
            <FilterBarChipMenu nodeId={node.id} wrapType={wrapType} canAddProperty />
            <Button
                size="icon"
                variant="outline"
                aria-label={`Remove ${name} filter`}
                tooltip="Remove filter"
                onClick={() => removeItem(node.id)}
                data-attr="filter-bar-chip-remove"
            >
                <IconX />
            </Button>
        </ButtonGroup>
    )
}
