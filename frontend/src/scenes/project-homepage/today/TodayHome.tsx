import './Today.scss'

import { useMountedLogic, useValues } from 'kea'

import { TodayBriefing } from './TodayBriefing'
import { todayDrawersLogic } from './todayDrawersLogic'
import { TodayEvidenceDrawers } from './TodayEvidenceDrawers'
import { TodayFollowUpPage } from './TodayFollowUpPage'
import { TodayLibrary } from './TodayLibrary'
import { todayLogic } from './todayLogic'
import { TodayNewFlow } from './TodayNewFlow'
import { TodayReportMissing, TodayReportPage } from './TodayReportPage'

/** The Today homepage: the daily briefing, a report, its follow-up, the New flow, or the Library, picked from the URL. */
export function TodayHome(): JSX.Element {
    useMountedLogic(todayDrawersLogic)
    const { route, currentReport, reportsReady } = useValues(todayLogic)

    let content: JSX.Element
    if (route.view === 'new') {
        content = <TodayNewFlow />
    } else if (route.view === 'library') {
        content = <TodayLibrary />
    } else if (route.view === 'report' || route.view === 'follow-up') {
        if (!reportsReady) {
            content = <div className="TodayReport" />
        } else if (!currentReport) {
            content = <TodayReportMissing />
        } else if (route.view === 'follow-up') {
            content = <TodayFollowUpPage key={`follow-up-${currentReport.id}`} report={currentReport} />
        } else {
            content = <TodayReportPage key={currentReport.id} report={currentReport} />
        }
    } else {
        content = <TodayBriefing />
    }

    return (
        <div className="Today flex-1 min-h-full @container/today">
            {content}
            <TodayEvidenceDrawers />
        </div>
    )
}
