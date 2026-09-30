import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { TodayAskBox } from './TodayAskBox'
import { TodayIcon } from './TodayIcon'
import { todayLogic } from './todayLogic'
import { TodaySampleBanner } from './TodaySampleBanner'
import { TodayBriefingSegment, reportIcon, reportSource } from './todaySignalReports'

const DATE_FORMAT = new Intl.DateTimeFormat(undefined, { weekday: 'short', day: 'numeric', month: 'short' })
const TIME_FORMAT = new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' })

function TodayMetaLine(): JSX.Element {
    const { now, currentTeam } = useValues(todayLogic)
    const date = new Date(now)
    return (
        <div className="TodayHome__meta">
            <span>{`${currentTeam?.name ?? 'Your project'} · ${DATE_FORMAT.format(date)} · `}</span>
            <time translate="no">{TIME_FORMAT.format(date)}</time>
        </div>
    )
}

function BriefingSegment({ segment }: { segment: TodayBriefingSegment }): JSX.Element {
    const { hoveredReportId, reports } = useValues(todayLogic)
    const { reportOpened, setHoveredReportId } = useActions(todayLogic)
    const { reportId } = segment
    if (!reportId) {
        return <span>{segment.text}</span>
    }
    // A briefing can link a report outside the top five, which has no row to open it from.
    const report = reports.find((candidate) => candidate.id === reportId)
    const link = (
        <Link
            to={urls.todayReport(reportId)}
            subtle
            className="TodayReportLink"
            data-active={hoveredReportId === reportId}
            data-attr="today-briefing-report"
            onClick={() => report && reportOpened(report, 'briefing')}
            onMouseEnter={() => setHoveredReportId(reportId)}
            onMouseLeave={() => setHoveredReportId(null)}
        >
            {segment.text}
        </Link>
    )
    return segment.highlight ? <span className="TodayHome__highlight">{link}</span> : link
}

function TodayBriefingReports(): JSX.Element {
    const { reportSummary, reports, briefing, hoveredReportId, moreReportCount } = useValues(todayLogic)
    const { askAi, openReport, setHoveredReportId } = useActions(todayLogic)

    return (
        <>
            <p className="TodayHome__count">
                <span>{reportSummary}</span>
                <span className="TodayChipStack">
                    {reports.map((report, index) => (
                        <button
                            key={report.id}
                            type="button"
                            className="TodayChipStack__chip"
                            aria-label={`Open ${report.title ?? 'report'}`}
                            data-active={hoveredReportId === report.id}
                            data-attr="today-briefing-chip"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={
                                {
                                    '--index': index,
                                    '--tilt': index % 2 === 0 ? '-3deg' : '3deg',
                                    '--report-color': reportSource(report).color,
                                } as React.CSSProperties
                            }
                            onClick={() => openReport(report, 'chip')}
                            onMouseEnter={() => setHoveredReportId(report.id)}
                            onMouseLeave={() => setHoveredReportId(null)}
                        >
                            <TodayIcon icon={reportIcon(report)} />
                        </button>
                    ))}
                </span>
            </p>
            {briefing.map((paragraph, index) => (
                <p key={index}>
                    {paragraph.map((segment, segmentIndex) => (
                        <BriefingSegment key={segmentIndex} segment={segment} />
                    ))}
                </p>
            ))}
            <p className="TodayHome__foot">
                {moreReportCount > 0 && (
                    <>
                        <Link to={urls.inbox()} data-attr="today-briefing-inbox">
                            {`${moreReportCount} more ${moreReportCount === 1 ? 'report is' : 'reports are'} in the Inbox`}
                        </Link>
                        <span>. </span>
                    </>
                )}
                <span>Or </span>
                <button
                    type="button"
                    data-attr="today-ask-about-edition"
                    onClick={() => askAi('Walk me through what changed in my product today.')}
                >
                    ask PostHog AI to walk you through it
                </button>
                <span>.</span>
            </p>
        </>
    )
}

export function TodayBriefing(): JSX.Element {
    const { greeting, topReports, topReportsLoading, reportsFailed, reports } = useValues(todayLogic)
    const { loadTopReports } = useActions(todayLogic)

    return (
        <div className="TodayHome Today__page">
            <TodaySampleBanner />
            <TodayMetaLine />
            <section className="TodayHome__intro" aria-label="Daily brief">
                <div className="TodayHome__greeting">{greeting}</div>
                {topReports === null && reportsFailed ? (
                    <LemonBanner
                        type="error"
                        action={{
                            children: 'Try again',
                            onClick: () => loadTopReports(),
                            loading: topReportsLoading,
                            'data-attr': 'today-reports-retry',
                        }}
                    >
                        Couldn’t load your reports. Try again, or open the Inbox to see them there.
                    </LemonBanner>
                ) : topReports === null ? (
                    <p>Reading what changed in your project…</p>
                ) : reports.length === 0 ? (
                    <>
                        <p className="TodayHome__count">Nothing needs your attention</p>
                        <p>
                            <span>
                                Self-driving turns signals from across PostHog into reports worth acting on. New ones
                                show up here as it finds them.{' '}
                            </span>
                            <Link to={urls.inbox()} data-attr="today-empty-inbox">
                                Open the Inbox
                            </Link>
                            <span> to see everything it’s tracking.</span>
                        </p>
                    </>
                ) : (
                    <TodayBriefingReports />
                )}
            </section>
            <TodayAskBox />
        </div>
    )
}
