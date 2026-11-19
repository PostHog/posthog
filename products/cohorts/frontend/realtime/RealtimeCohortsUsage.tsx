import { useValues } from 'kea'

import { pluralize } from 'lib/utils/strings'
import { teamLogic } from 'scenes/teamLogic'

import { RealtimePlanLimitsLink } from './RealtimePlanLimitsLink'

/** How many of the cohorts the plan allows have realtime on in this project. Nothing when the plan sets no limit. */
export function RealtimeCohortsUsage({
    location,
}: {
    location: 'cohort_page' | 'cohort_create' | 'flag_editor'
}): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const { cohorts_used: used, max_cohorts: allowed } = currentTeam?.realtime_cohorts ?? {}
    if (used == null || allowed == null) {
        return null
    }

    return (
        <div className="flex items-center gap-x-2 flex-wrap text-secondary" data-attr="cohort-realtime-usage">
            <span>{`Your plan allows realtime for ${pluralize(allowed, 'cohort')} in this project, and it is on for ${used}.`}</span>
            {used >= allowed && <RealtimePlanLimitsLink limit="cohorts" location={location} />}
        </div>
    )
}
