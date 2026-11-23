import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { SESSION_REPLAY_MINIMUM_DURATION_OPTIONS, TeamMembershipLevel } from 'lib/constants'
import { LemonSelectOptionLeaf } from 'lib/lemon-ui/LemonSelect'

const NO_MINIMUM = 'none'

const OPTIONS = (SESSION_REPLAY_MINIMUM_DURATION_OPTIONS as LemonSelectOptionLeaf<number | null>[]).map((option) => ({
    key: option.value === null ? NO_MINIMUM : String(option.value),
    value: option.value,
    label: option.label,
}))

export function QuillMinDurationTrigger({
    value,
    onChange,
}: {
    value: number | null | undefined
    onChange: (value: number | null | undefined) => void
}): JSX.Element {
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const selectedKey = value == null ? NO_MINIMUM : String(value)

    return (
        <Select
            value={selectedKey}
            onValueChange={(key) => onChange(OPTIONS.find((option) => option.key === key)?.value ?? null)}
        >
            <SelectTrigger aria-label="Minimum duration" disabledReason={restrictedReason}>
                <SelectValue>{(key: string) => OPTIONS.find((option) => option.key === key)?.label}</SelectValue>
            </SelectTrigger>
            <SelectContent>
                {OPTIONS.map((option) => (
                    <SelectItem key={option.key} value={option.key}>
                        {option.label}
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    )
}
