import { useActions, useValues } from 'kea'

import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'

import { TodayAskBox } from './TodayAskBox'
import { TodayIcon } from './TodayIcon'
import { todayLogic } from './todayLogic'
import { TodayBriefingSegment } from './todayTypes'

const DATE_FORMAT = new Intl.DateTimeFormat('en-GB', { weekday: 'short', day: '2-digit', month: 'short' })
const TIME_FORMAT = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' })

function TodayMetaLine(): JSX.Element {
    const { now, currentTeam, usingSampleReports } = useValues(todayLogic)
    const date = new Date(now)
    return (
        <div className="TodayHome__meta">
            <span>{`${currentTeam?.name ?? 'Your project'} · ${DATE_FORMAT.format(date)} · `}</span>
            <time translate="no">{TIME_FORMAT.format(date)}</time>
            {usingSampleReports && <span className="TodayHome__sample">Sample reports</span>}
        </div>
    )
}

function BriefingSegment({ segment }: { segment: TodayBriefingSegment }): JSX.Element {
    const { hoveredReportId } = useValues(todayLogic)
    const { openReport, setHoveredReportId } = useActions(todayLogic)
    const reportId = segment.link
    if (!reportId) {
        return <span>{segment.text}</span>
    }
    const link = (
        <button
            type="button"
            className="TodayReportLink"
            data-active={hoveredReportId === reportId}
            onClick={() => openReport(reportId)}
            onMouseEnter={() => setHoveredReportId(reportId)}
            onMouseLeave={() => setHoveredReportId(null)}
            onFocus={() => setHoveredReportId(reportId)}
            onBlur={() => setHoveredReportId(null)}
        >
            {segment.text}
        </button>
    )
    return segment.highlight ? <span className="TodayHome__highlight">{link}</span> : link
}

export function TodayBriefing(): JSX.Element {
    const { greeting, reportSummary, reports, briefing, hoveredReportId, reportsReady } = useValues(todayLogic)
    const { openReport, setHoveredReportId } = useActions(todayLogic)
    const { askSidePanelMax } = useActions(maxGlobalLogic)
    const chips = reports.filter((report) => !report.secondary).slice(0, 6)

    return (
        <div className="TodayHome Today__page">
            <TodayMetaLine />
            <section className="TodayHome__intro" aria-label="Daily brief">
                <div className="TodayHome__greeting">{greeting}</div>
                {reportsReady ? (
                    <>
                        <p className="TodayHome__count">
                            <span>{reportSummary}</span>
                            {chips.length > 0 && (
                                <span className="TodayChipStack">
                                    {chips.map((report, index) => (
                                        <button
                                            key={report.id}
                                            type="button"
                                            className="TodayChipStack__chip"
                                            aria-label={`Open ${report.title}`}
                                            data-active={hoveredReportId === report.id}
                                            // eslint-disable-next-line react/forbid-dom-props
                                            style={
                                                {
                                                    '--index': index,
                                                    '--tilt': index % 2 === 0 ? '-3deg' : '3deg',
                                                    '--report-color': report.color,
                                                } as React.CSSProperties
                                            }
                                            onClick={() => openReport(report.id)}
                                            onMouseEnter={() => setHoveredReportId(report.id)}
                                            onMouseLeave={() => setHoveredReportId(null)}
                                            onFocus={() => setHoveredReportId(report.id)}
                                            onBlur={() => setHoveredReportId(null)}
                                        >
                                            <TodayIcon report={report.icon} />
                                        </button>
                                    ))}
                                </span>
                            )}
                        </p>
                        {briefing.map((paragraph, index) => (
                            <p key={index}>
                                {paragraph.map((segment, segmentIndex) => (
                                    <BriefingSegment key={segmentIndex} segment={segment} />
                                ))}
                            </p>
                        ))}
                        <p className="TodayHome__foot">
                            <span>Or </span>
                            <button
                                type="button"
                                data-attr="today-ask-about-edition"
                                onClick={() => askSidePanelMax('Walk me through what changed in my product today.')}
                            >
                                ask PostHog AI to walk you through it
                            </button>
                            <span>.</span>
                        </p>
                    </>
                ) : (
                    <p>Reading what changed in your project…</p>
                )}
            </section>
            <TodayAskBox />
        </div>
    )
}
