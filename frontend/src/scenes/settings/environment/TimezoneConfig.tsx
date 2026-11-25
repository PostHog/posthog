import { useActions, useValues } from 'kea'

import { Skeleton } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { timeZoneLabel } from 'lib/utils/timezones'
import { teamLogic } from 'scenes/teamLogic'

import { QuillTimezoneCombobox } from './QuillTimezoneCombobox'

export function TimezoneConfig({
    displayWarning = true,
    id,
}: {
    displayWarning?: boolean
    /** Lets a field label point at the time zone search input. */
    id?: string
}): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const { currentTeam, timezone: currentTimezone, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!preflight?.available_timezones || !currentTeam) {
        return todayRailNav ? <Skeleton className="h-8 w-1/2" /> : <LemonSkeleton className="w-1/2 h-4" />
    }
    const options = Object.entries(preflight.available_timezones).map(([tz, offset]) => ({
        key: tz,
        label: timeZoneLabel(tz, offset),
    }))

    const handleChange = (newTimezone: string | undefined): void => {
        // This is a string for a single-mode select, but typing is poor
        // Backspace on an empty input clears the selection, but a time zone is always required
        if (!newTimezone) {
            return
        }
        if (!preflight?.available_timezones) {
            throw new Error('No timezones are available')
        }
        const currentOffset = preflight.available_timezones[currentTimezone]
        const newOffset = preflight.available_timezones[newTimezone]
        if (currentOffset === newOffset || !displayWarning) {
            updateCurrentTeam({ timezone: newTimezone })
        } else {
            LemonDialog.open({
                title: `Change time zone to ${timeZoneLabel(newTimezone, newOffset)}?`,
                description: (
                    <p className="max-w-120">
                        This time zone has an offset different from the current{' '}
                        <strong>{timeZoneLabel(currentTimezone, currentOffset)}</strong>, so queries will need to be
                        recalculated. There will be a difference in date-based time ranges, and in day/week/month
                        buckets.
                    </p>
                ),
                primaryButton: {
                    children: 'Change time zone',
                    onClick: () => updateCurrentTeam({ timezone: newTimezone }),
                },
                secondaryButton: {
                    children: 'Cancel',
                },
            })
        }
    }

    if (todayRailNav) {
        return (
            <QuillTimezoneCombobox
                id={id}
                options={options}
                value={currentTeam.timezone}
                onChange={handleChange}
                disabled={currentTeamLoading}
                disabledReason={restrictedReason}
            />
        )
    }

    return (
        <div className="max-w-160">
            <LemonInputSelect
                mode="single"
                placeholder="Select a time zone"
                disabled={currentTeamLoading || !!restrictedReason}
                value={[currentTeam.timezone]}
                popoverClassName="z-[1000]"
                virtualized
                onChange={([newTimezone]): void => handleChange(newTimezone)}
                options={options}
                data-attr="timezone-select"
            />
        </div>
    )
}
