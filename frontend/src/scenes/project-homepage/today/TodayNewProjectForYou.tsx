import { useValues } from 'kea'

import { todayGetStartedLogic } from './todayGetStartedLogic'
import { TodayHomeHeading } from './TodayHomeHeading'
import { TodaySetupRow } from './TodaySetupRow'

export function TodayNewProjectForYou(): JSX.Element | null {
    const { stepsReady, allDone, hidden } = useValues(todayGetStartedLogic)

    if (!stepsReady || allDone || hidden) {
        return null
    }
    return (
        <section className="TodayHome__list" aria-label="For you today">
            <div className="TodayHome__headingRow">
                <TodayHomeHeading>For you today</TodayHomeHeading>
            </div>
            <TodaySetupRow />
        </section>
    )
}
