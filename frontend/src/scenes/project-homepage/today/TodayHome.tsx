import { useValues } from 'kea'

import { TodayQuillRoot } from '~/layout/today/TodayQuillRoot'

import { TodayBriefing } from './TodayBriefing'
import { todayLogic } from './todayLogic'
import { TodayReportPage } from './TodayReportPage'

/** The Today homepage: the daily briefing at `/home`, or one report at `/home/reports/:reportId`. */
export function TodayHome(): JSX.Element {
    const { reportId } = useValues(todayLogic)

    return (
        <TodayQuillRoot className="flex min-h-full flex-1 flex-col @container/today">
            <div className="flex-1 bg-background px-6 py-12 @2xl/today:px-16 @2xl/today:py-20">
                <div className="mx-auto flex w-full max-w-3xl flex-col gap-8">
                    {reportId ? <TodayReportPage key={reportId} reportId={reportId} /> : <TodayBriefing />}
                </div>
            </div>
        </TodayQuillRoot>
    )
}
