import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'
import { Button, Skeleton } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TagsCombobox } from 'lib/components/Scenes/TagsCombobox'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { teamLogic } from 'scenes/teamLogic'

export function DataAttributes(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const [value, setValue] = useState([] as string[])
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    useEffect(() => setValue(currentTeam?.data_attributes || []), [currentTeam])

    const handleSave = (): void =>
        updateCurrentTeam({ data_attributes: value.map((s) => s.trim()).filter((a) => a) || [] })

    if (!currentTeam) {
        return todayRailNav ? <Skeleton className="h-8 max-w-160" /> : <LemonSkeleton />
    }

    if (todayRailNav) {
        return (
            <div className="flex flex-col items-start gap-2 max-w-160">
                <TagsCombobox
                    value={value}
                    onChange={setValue}
                    customValueNoun="data attribute"
                    dataAttr="data-attribute-select"
                    placeholder="data-attr, ..."
                    disabled={currentTeamLoading}
                    disabledReason={restrictedReason}
                    className="w-full"
                />
                <Button variant="primary" onClick={handleSave} disabledReason={restrictedReason}>
                    Save
                </Button>
            </div>
        )
    }

    return (
        <>
            <div className="deprecated-space-y-4 max-w-160">
                <LemonInputSelect
                    mode="multiple"
                    allowCustomValues
                    onChange={(values: string[]) => setValue(values || [])}
                    value={value}
                    data-attr="data-attribute-select"
                    placeholder="data-attr, ..."
                    loading={currentTeamLoading}
                    disabled={currentTeamLoading || !!restrictedReason}
                />
                <LemonButton type="primary" onClick={handleSave} disabledReason={restrictedReason}>
                    Save
                </LemonButton>
            </div>
        </>
    )
}
