import { useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Popover } from 'lib/lemon-ui/Popover/Popover'

export interface AddEventButtonProps {
    onEventSelect: (eventName: string) => void
    addButtonText?: string
    excludedEvents?: string[]
}

export function AddEventButton({
    onEventSelect,
    addButtonText,
    excludedEvents = [],
}: AddEventButtonProps): JSX.Element {
    const [popoverOpen, setPopoverOpen] = useState(false)

    return (
        <Popover
            overlay={
                <TaxonomicFilter
                    groupType={TaxonomicFilterGroupType.Events}
                    value=""
                    onChange={(_, value) => {
                        if (typeof value === 'string') {
                            const eventName = value

                            if (!excludedEvents.includes(eventName)) {
                                onEventSelect(eventName)
                            }
                            setPopoverOpen(false)
                        }
                    }}
                    allowNonCapturedEvents
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.CustomEvents, TaxonomicFilterGroupType.Events]}
                />
            }
            visible={popoverOpen}
            onClickOutside={() => setPopoverOpen(false)}
            placement="bottom-start"
        >
            <LemonButton
                type="secondary"
                icon={<IconPlus />}
                onClick={() => setPopoverOpen(!popoverOpen)}
                size="small"
                className="w-fit"
            >
                {addButtonText ?? 'Add event'}
            </LemonButton>
        </Popover>
    )
}
