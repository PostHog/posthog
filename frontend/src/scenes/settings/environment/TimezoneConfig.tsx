import { useActions, useValues } from 'kea'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { timeZoneLabel } from 'lib/utils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { teamLogic } from 'scenes/teamLogic'

export function TimezoneConfig(): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const { currentTeam, timezone: currentTimezone, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    if (!preflight?.available_timezones || !currentTeam) {
        return <LemonSkeleton className="w-1/2 h-4" />
    }
    const options = Object.entries(preflight.available_timezones).map(([tz, offset]) => ({
        key: tz,
        label: timeZoneLabel(tz, offset),
    }))

    return (
        <div className="max-w-160">
            <LemonInputSelect
                mode="single"
                placeholder="Select a time zone"
                loading={currentTeamLoading}
                disabled={currentTeamLoading}
                value={[currentTeam.timezone]}
                popoverClassName="z-[1000]"
                virtualized
                onChange={([newTimezone]): void => {
                    // This is a string for a single-mode select, but typing is poor
                    if (!preflight?.available_timezones) {
                        throw new Error('No timezones are available')
                    }
                    const currentOffset = preflight.available_timezones[currentTimezone]
                    const newOffset = preflight.available_timezones[newTimezone]
                    if (currentOffset === newOffset) {
                        updateCurrentTeam({ timezone: newTimezone })
                    } else {
                        LemonDialog.open({
                            title: `Change time zone to ${timeZoneLabel(newTimezone, newOffset)}?`,
                            description: (
                                <p className="max-w-120">
                                    This time zone has an offset different from the current{' '}
                                    <strong>{timeZoneLabel(currentTimezone, currentOffset)}</strong>, so queries will
                                    need to be recalculated. There will be a difference in date-based time ranges, and
                                    in day/week/month buckets.
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
                }}
                options={options}
                data-attr="timezone-select"
            />
        </div>
    )
}
