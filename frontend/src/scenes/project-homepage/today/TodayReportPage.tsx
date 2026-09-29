import { useActions } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { TodayAskBox } from './TodayAskBox'
import { TodayEvidenceStack } from './TodayEvidenceStack'
import { TodayIcon } from './TodayIcon'
import { todayLogic } from './todayLogic'
import { TodayNextStep } from './TodayNextStep'
import { TodayReport } from './todayTypes'

export function TodayReportHeader({ kicker, icon }: { kicker: string; icon: JSX.Element | null }): JSX.Element {
    return (
        <div className="TodayReport__kicker">
            <span className="TodayTile">{icon}</span>
            <span>{kicker}</span>
        </div>
    )
}

export function TodayReportPage({ report }: { report: TodayReport }): JSX.Element {
    return (
        <div
            className="TodayReport Today__page"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ '--report-color': report.color } as React.CSSProperties}
        >
            <article>
                <TodayReportHeader kicker={report.title} icon={<TodayIcon report={report.icon} />} />
                <h1 className="TodayReport__heading">{report.heading}</h1>
                <div className="TodayReport__body">
                    {report.paragraphs.map((paragraph, index) => (
                        <p key={index}>{paragraph}</p>
                    ))}
                </div>
            </article>
            <TodayNextStep report={report} />
            <TodayEvidenceStack report={report} />
            <TodayAskBox compact />
        </div>
    )
}

export function TodayReportMissing(): JSX.Element {
    const { openHome } = useActions(todayLogic)
    return (
        <div className="TodayReport Today__page">
            <h1 className="TodayReport__heading">This report is no longer on your list.</h1>
            <div className="TodayReport__body">
                <p>It may have been resolved or removed. Head back to today’s briefing to see what still needs you.</p>
            </div>
            <div className="mt-6">
                <LemonButton type="primary" onClick={openHome} data-attr="today-report-missing-home">
                    Back to Home
                </LemonButton>
            </div>
        </div>
    )
}
