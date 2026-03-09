import { useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonSnack, Popover } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TeamMembershipLevel } from 'lib/constants'
import { isStringWithLength } from 'scenes/settings/environment/replayTriggersLogic'

export function EventTriggerSelect({
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
        <Popover
            visible={open}
            onClickOutside={() => setOpen(false)}
            overlay={
                <TaxonomicFilter
                    onChange={(_, value) => {
                        if (isStringWithLength(value)) {
                            onChange(Array.from(new Set(events?.concat([value]))))
                        }
                        setOpen(false)
                    }}
                    excludedProperties={{
                        [TaxonomicFilterGroupType.Events]: [null], // This will hide "All events"
                    }}
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.Events]}
                />
            }
        >
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconPlus />}
                sideIcon={null}
                onClick={() => setOpen(!open)}
                disabledReason={restrictedReason}
            >
                Add event
            </LemonButton>
        </Popover>
    )
}

export function EventTrigger({ trigger, onClose }: { trigger: string; onClose: () => void }): JSX.Element {
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    return <LemonSnack onClose={!restrictedReason ? () => onClose() : undefined}>{trigger}</LemonSnack>
}
