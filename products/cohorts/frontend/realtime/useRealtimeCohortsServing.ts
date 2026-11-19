import { useValues } from 'kea'

import { teamLogic } from 'scenes/teamLogic'

/** Whether this project's users see realtime cohorts: whether flags can target each cohort, and the switch for it. */
export function useRealtimeCohortsServing(): boolean {
    const { currentTeam } = useValues(teamLogic)
    return currentTeam?.realtime_cohorts?.access === 'serving'
}
