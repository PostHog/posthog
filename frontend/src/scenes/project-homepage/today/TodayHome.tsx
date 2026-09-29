import './Today.scss'

import { useValues } from 'kea'

import { TodayBriefing } from './TodayBriefing'
import { todayLogic } from './todayLogic'
import { TodayReportPage } from './TodayReportPage'

/** The Today homepage: the daily briefing at `/home`, or one report at `/home/reports/:reportId`. */
export function TodayHome(): JSX.Element {
    const { reportId } = useValues(todayLogic)

    return (
        <div className="Today flex-1 min-h-full @container/today">
            {reportId ? <TodayReportPage key={reportId} reportId={reportId} /> : <TodayBriefing />}
        </div>
    )
}
