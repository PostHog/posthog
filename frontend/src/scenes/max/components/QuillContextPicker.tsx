import { useActions, useValues } from 'kea'
import { useId, useState } from 'react'

import { IconAtSign } from '@posthog/icons'
import { Button, Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'

import { maxContextLogic } from '../maxContextLogic'
import { maxThreadLogic } from '../maxThreadLogic'

/**
 * The legacy chat's context picker in the quill composer: the same taxonomic filter as the lemon
 * `TaxonomicPopover`, in a quill popover with a quill trigger, bound to `maxContextLogic`.
 */
export function QuillContextPicker(): JSX.Element {
    const [open, setOpen] = useState(false)
    const filterKey = `posthog-ai-legacy-context-picker-${useId()}`
    const { contextDisabledReason } = useValues(maxThreadLogic)
    const { hasData, contextOptions, taxonomicGroupTypes, mainTaxonomicGroupType, toolContextItems } =
        useValues(maxContextLogic)
    const { handleTaxonomicFilterChange, openContextPicker } = useActions(maxContextLogic)
    const showLabel = !hasData && toolContextItems.length === 0

    return (
        <Popover
            open={open}
            onOpenChange={(next) => {
                if (next) {
                    openContextPicker()
                }
                setOpen(next)
            }}
        >
            <PopoverTrigger
                render={
                    <Button
                        variant="default"
                        size={showLabel ? 'sm' : 'icon-sm'}
                        aria-label="Add context"
                        tooltip="Add context to help PostHog AI answer your question"
                        disabledReason={contextDisabledReason}
                        data-attr="max-context-picker"
                    >
                        <IconAtSign />
                        {showLabel && <span className="@max-[480px]/composer:hidden">Add context</span>}
                    </Button>
                }
            />
            <PopoverContent side="top" align="start" className="w-auto p-0">
                {/* The filter is Lemon, so it keeps Lemon's colors inside the quill popover. */}
                <div data-not-quill>
                    <TaxonomicFilter
                        taxonomicFilterLogicKey={filterKey}
                        groupType={mainTaxonomicGroupType}
                        taxonomicGroupTypes={taxonomicGroupTypes}
                        maxContextOptions={contextOptions}
                        onChange={({ type }, value, item) => {
                            if (value !== null) {
                                handleTaxonomicFilterChange(value, type, item)
                            }
                            setOpen(false)
                        }}
                        onClose={() => setOpen(false)}
                        width={450}
                    />
                </div>
            </PopoverContent>
        </Popover>
    )
}
