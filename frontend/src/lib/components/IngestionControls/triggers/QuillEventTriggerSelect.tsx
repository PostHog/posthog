import { useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { Button, Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TeamMembershipLevel } from 'lib/constants'

import { isStringWithLength } from './urlConfigLogic'

export function QuillEventTriggerSelect({
    events,
    onChange,
}: {
    events: string[] | null
    onChange: (eventTriggerConfig: string[]) => void
}): JSX.Element {
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const [open, setOpen] = useState<boolean>(false)

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger
                render={
                    <Button variant="outline" disabledReason={restrictedReason}>
                        <IconPlus />
                        Add event
                    </Button>
                }
            />
            <PopoverContent align="end" className="w-auto p-0">
                {/* The filter is Lemon, so it keeps Lemon's colors inside the quill popover. */}
                <div data-not-quill>
                    <TaxonomicFilter
                        onChange={(_, value) => {
                            if (isStringWithLength(value)) {
                                onChange(Array.from(new Set(events?.concat([value]))))
                            }
                            setOpen(false)
                        }}
                        onClose={() => setOpen(false)}
                        excludedProperties={{
                            [TaxonomicFilterGroupType.Events]: [null], // This will hide "All events"
                        }}
                        taxonomicGroupTypes={[TaxonomicFilterGroupType.Events]}
                        // Chooses which live events to act on rather than saving a query.
                        includeHiddenEvents
                    />
                </div>
            </PopoverContent>
        </Popover>
    )
}
