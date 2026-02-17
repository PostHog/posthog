import { useActions, useValues } from 'kea'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

import { teamLogic } from '~/scenes/teamLogic'

const DEFAULT_RECALCULATION_UTC_HOUR = 2 // 02:00 UTC default

const formatHourString = (hour: number): string => {
    return dayjs().hour(hour).format('HH:00')
}

const hourOptions = Array.from({ length: 24 }, (_, hour) => ({
    value: hour.toString(),
    label: formatHourString(hour),
}))

const utcToLocalHour = (utcTimeString: string | null | undefined, projectTimezone: string): number => {
    if (!utcTimeString) {
        const defaultTime = dayjs.utc().hour(DEFAULT_RECALCULATION_UTC_HOUR)
        return defaultTime.tz(projectTimezone).hour()
    }

    const [hour] = utcTimeString.split(':').map(Number)
    const utcTime = dayjs.utc().hour(hour)
    return utcTime.tz(projectTimezone).hour()
}

const localHourToUtcString = (localHour: number, projectTimezone: string): string => {
    const localTime = dayjs().tz(projectTimezone).hour(localHour).minute(0).second(0).millisecond(0)
    return localTime.utc().format('HH:mm:ss')
}

export function ExperimentRecalculationTime(): JSX.Element {
    const { currentTeam, currentTeamLoading, timezone: projectTimezone } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    const handleChange = (value: string): void => {
        const localHour = parseInt(value, 10)
        const utcTimeString = localHourToUtcString(localHour, projectTimezone)
        updateCurrentTeam({ experiment_recalculation_time: utcTimeString })
    }

    const currentLocalHour = utcToLocalHour(currentTeam?.experiment_recalculation_time, projectTimezone)

    return (
        <LemonSelect
            value={currentLocalHour.toString()}
            onChange={handleChange}
            options={hourOptions}
            disabledReason={restrictionReason || (currentTeamLoading ? 'Loading...' : undefined)}
            data-attr="team-experiment-recalculation-time"
            placeholder="Select recalculation time"
        />
    )
}
