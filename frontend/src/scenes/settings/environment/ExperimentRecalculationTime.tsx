import { useActions, useValues } from 'kea'

import { IconPlus, IconX } from '@posthog/icons'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { FEATURE_FLAGS, TeamMembershipLevel } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSelect, LemonSelectOption } from 'lib/lemon-ui/LemonSelect'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { teamLogic } from '~/scenes/teamLogic'

import { experimentsConfigLogic } from './experimentsConfigLogic'

const DEFAULT_RECALCULATION_UTC_TIME = '02:00:00'
// Must match MIN_RECALCULATION_GAP_HOURS in products/experiments/backend/models/team_experiments_config.py
const MIN_RECALCULATION_GAP_HOURS = 6

const utcHourFromTimeString = (utcTimeString: string): number => parseInt(utcTimeString.split(':')[0], 10)

const utcTimeStringFromUtcHour = (utcHour: number): string => `${String(utcHour).padStart(2, '0')}:00:00`

const circularHourGap = (hourA: number, hourB: number): number => {
    const diff = Math.abs(hourA - hourB)
    return Math.min(diff, 24 - diff)
}

const utcToLocalHour = (utcTimeString: string, projectTimezone: string): number => {
    const utcTime = dayjs.utc().hour(utcHourFromTimeString(utcTimeString))
    return utcTime.tz(projectTimezone).hour()
}

const localHourToUtcString = (localHour: number, projectTimezone: string): string => {
    const localTime = dayjs().tz(projectTimezone).hour(localHour).minute(0).second(0).millisecond(0)
    // Floored to the hour: half-hour timezones would otherwise produce times the API rejects
    return localTime.utc().format('HH:00:00')
}

export function ExperimentRecalculationTime(): JSX.Element {
    const { timezone: projectTimezone } = useValues(teamLogic)
    const { experimentsConfig, experimentsConfigLoading } = useValues(experimentsConfigLogic)
    const { updateExperimentsConfig } = useActions(experimentsConfigLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const allowSecondTime = !!featureFlags[FEATURE_FLAGS.EXPERIMENT_MULTIPLE_RECALCULATION_TIMES]

    const savedTimes = experimentsConfig?.experiment_recalculation_times?.length
        ? experimentsConfig.experiment_recalculation_times
        : [DEFAULT_RECALCULATION_UTC_TIME]
    const times = allowSecondTime ? savedTimes : [savedTimes[0]]

    const commonDisabledReason = restrictedReason || (experimentsConfigLoading ? 'Loading...' : undefined)

    const handleTimeChange = (index: number, value: string): void => {
        const newTimes = [...times]
        newTimes[index] = localHourToUtcString(parseInt(value, 10), projectTimezone)
        updateExperimentsConfig({ experiment_recalculation_times: newTimes })
    }

    const addSecondTime = (): void => {
        const oppositeUtcHour = (utcHourFromTimeString(times[0]) + 12) % 24
        updateExperimentsConfig({
            experiment_recalculation_times: [times[0], utcTimeStringFromUtcHour(oppositeUtcHour)],
        })
    }

    const removeSecondTime = (): void => {
        updateExperimentsConfig({ experiment_recalculation_times: [times[0]] })
    }

    const optionsForIndex = (index: number): LemonSelectOption<string>[] => {
        const otherTime = times.length > 1 ? times[1 - index] : null
        const otherUtcHour = otherTime !== null ? utcHourFromTimeString(otherTime) : null
        return Array.from({ length: 24 }, (_, localHour) => {
            const utcHour = utcHourFromTimeString(localHourToUtcString(localHour, projectTimezone))
            const tooClose =
                otherUtcHour !== null && circularHourGap(utcHour, otherUtcHour) < MIN_RECALCULATION_GAP_HOURS
            return {
                value: localHour.toString(),
                label: dayjs().hour(localHour).format('HH:00'),
                disabledReason: tooClose
                    ? `Must be at least ${MIN_RECALCULATION_GAP_HOURS} hours from the other recalculation time`
                    : undefined,
            }
        })
    }

    return (
        <div className="flex items-center gap-2">
            <LemonSelect
                value={utcToLocalHour(times[0], projectTimezone).toString()}
                onChange={(value) => handleTimeChange(0, value)}
                options={optionsForIndex(0)}
                disabledReason={commonDisabledReason}
                data-attr="team-experiment-recalculation-time"
                placeholder="Select recalculation time"
            />
            {allowSecondTime &&
                (times.length > 1 ? (
                    <>
                        <LemonSelect
                            value={utcToLocalHour(times[1], projectTimezone).toString()}
                            onChange={(value) => handleTimeChange(1, value)}
                            options={optionsForIndex(1)}
                            disabledReason={commonDisabledReason}
                            data-attr="team-experiment-second-recalculation-time"
                        />
                        <LemonButton
                            icon={<IconX />}
                            size="small"
                            onClick={removeSecondTime}
                            disabledReason={commonDisabledReason}
                            tooltip="Remove second time"
                            data-attr="team-experiment-remove-second-recalculation-time"
                        />
                    </>
                ) : (
                    <LemonButton
                        type="tertiary"
                        icon={<IconPlus />}
                        size="small"
                        onClick={addSecondTime}
                        disabledReason={commonDisabledReason}
                        data-attr="team-experiment-add-second-recalculation-time"
                    >
                        Add second time
                    </LemonButton>
                ))}
        </div>
    )
}
