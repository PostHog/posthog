import { Badge, Chip, ChipClose, Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType, TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'

export interface QuillEventSelectProps {
    selectedEvents: string[]
    addElement: JSX.Element
    open: boolean
    onOpenChange: (open: boolean) => void
    onSelect: (value: TaxonomicFilterValue, item: any) => void
    onRemove: (name: string) => void
    isNonCapturedEvent: (name: string) => boolean
    filterGroupTypes: TaxonomicFilterGroupType[]
    allowNonCapturedEvents: boolean
}

export function QuillEventSelect({
    selectedEvents,
    addElement,
    open,
    onOpenChange,
    onSelect,
    onRemove,
    isNonCapturedEvent,
    filterGroupTypes,
    allowNonCapturedEvents,
}: QuillEventSelectProps): JSX.Element {
    return (
        <div className="flex items-center flex-wrap gap-2">
            {selectedEvents.map((name) => (
                <Chip key={name}>
                    <span>{name}</span>
                    {isNonCapturedEvent(name) && <Badge variant="warning">Not captured yet</Badge>}
                    <ChipClose aria-label={`Remove ${name}`} onClick={() => onRemove(name)} />
                </Chip>
            ))}

            <Popover open={open} onOpenChange={onOpenChange}>
                <PopoverTrigger render={addElement} />
                <PopoverContent align="start" className="w-auto p-0">
                    {/* The filter is Lemon, so it keeps Lemon's colors inside the quill popover. */}
                    <div data-not-quill>
                        <TaxonomicFilter
                            onChange={(_, value, item) => onSelect(value, item)}
                            taxonomicGroupTypes={filterGroupTypes}
                            allowNonCapturedEvents={allowNonCapturedEvents}
                        />
                    </div>
                </PopoverContent>
            </Popover>
        </div>
    )
}
