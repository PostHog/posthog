import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { Heading, Select, SelectContent, SelectItem, SelectTrigger, SelectValue, Text } from '@posthog/quill'

import { TeamMembershipLevel } from 'lib/constants'

import { RestrictionScope, useRestrictedArea } from '../RestrictedArea'
import { ingestionControlsLogic } from './ingestionControlsLogic'

const MATCH_TYPE_OPTIONS: { value: 'all' | 'any'; title: string; description: string }[] = [
    { value: 'all', title: 'All', description: 'Every trigger must match' },
    { value: 'any', title: 'Any', description: 'One or more triggers must match' },
]

export function QuillMatchTypeSelect({
    lockedToAllReason,
    titleBadge,
}: {
    lockedToAllReason?: string
    titleBadge?: ReactNode
}): JSX.Element {
    const { matchType } = useValues(ingestionControlsLogic)
    const { onChangeMatchType } = useActions(ingestionControlsLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const displayedValue = lockedToAllReason ? 'all' : matchType
    const disabledReason = lockedToAllReason ?? restrictedReason

    return (
        <div className="flex flex-col gap-2">
            <Heading size="sm" render={<h3 className="m-0 flex items-center gap-1" />}>
                Trigger matching
                {titleBadge}
            </Heading>
            <div className="flex flex-wrap items-center gap-2">
                <Text size="xs" render={<span />}>
                    Start when
                </Text>
                <Select
                    value={displayedValue}
                    onValueChange={(value) => value && onChangeMatchType(value as 'all' | 'any')}
                >
                    <SelectTrigger
                        aria-label="Trigger matching"
                        data-attr="trigger-match-choice"
                        disabledReason={disabledReason}
                    >
                        <SelectValue>{(value: 'all' | 'any') => value}</SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                        {MATCH_TYPE_OPTIONS.map((option) => (
                            <SelectItem key={option.value} value={option.value}>
                                <span className="flex flex-col">
                                    <span>{option.title}</span>
                                    <Text size="xs" variant="muted" render={<span />}>
                                        {option.description}
                                    </Text>
                                </span>
                            </SelectItem>
                        ))}
                    </SelectContent>
                </Select>
                <Text size="xs" render={<span />}>
                    triggers below match
                </Text>
            </div>
        </div>
    )
}
