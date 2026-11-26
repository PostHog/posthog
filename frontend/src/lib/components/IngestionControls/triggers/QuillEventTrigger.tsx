import { Chip, ChipClose } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'

export function QuillEventTrigger({ trigger, onClose }: { trigger: string; onClose: () => void }): JSX.Element {
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    return (
        <Chip>
            {trigger}
            {!restrictedReason && <ChipClose aria-label={`Remove ${trigger}`} onClick={() => onClose()} />}
        </Chip>
    )
}
