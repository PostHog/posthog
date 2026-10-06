import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { TodayPreviewTrigger } from '~/layout/today/TodayPreviewTrigger'

import { TodayAskBox } from './TodayAskBox'
import { WALK_THROUGH_QUESTION } from './todayAskPrompt'
import { TodayBriefingFocusLine } from './TodayBriefingFocusLine'
import { TodayChipStack } from './TodayChipStack'
import { TodayIcon } from './TodayIcon'
import { todayLogic } from './todayLogic'
import { TodayPersonalBriefing } from './TodayPersonalBriefing'
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
    const { hoveredReportId, reports, teamReportPreviews, reportStateOverrides } = useValues(todayLogic)
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
            data-state={reportStateOverrides[reportId] ?? 'open'}
            data-attr="today-briefing-report"
            onClick={() => report && reportOpened(report, 'briefing')}
            onMouseEnter={() => setHoveredReportId(reportId)}
            onMouseLeave={() => setHoveredReportId(null)}
        >
            {segment.text}
        </Link>
    )
    const preview = teamReportPreviews.briefing[reportId]
    const linkWithCard = preview ? (
        <TodayPreviewTrigger payload={preview} inline>
            {link}
        </TodayPreviewTrigger>
    ) : (
        link
    )
    return segment.highlight ? <span className="TodayHome__highlight">{linkWithCard}</span> : linkWithCard
}

function TodayBriefingReports(): JSX.Element {
    const { reportSummary, reports, briefing, hoveredReportId, moreReportCount } = useValues(todayLogic)
    const { askAi, openReport, setHoveredReportId } = useActions(todayLogic)

    return (
        <>
            <p className="TodayHome__count">
                <span>{reportSummary}</span>
                <TodayChipStack
                    dataAttr="today-briefing-chip"
                    chips={reports.map((report) => ({
                        key: report.id,
                        label: report.title ?? 'report',
                        color: reportSource(report).color,
                        icon: <TodayIcon icon={reportIcon(report)} />,
                        active: hoveredReportId === report.id,
                        onClick: () => openReport(report, 'chip'),
                        onHoverChange: (hovered) => setHoveredReportId(hovered ? report.id : null),
                    }))}
                />
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
                            {`${moreReportCount} more for you in the Inbox`}
                        </Link>
                        <span>. </span>
                    </>
                )}
                <span>Or </span>
                <button
                    type="button"
                    data-attr="today-ask-about-edition"
                    onClick={() => askAi(WALK_THROUGH_QUESTION, 'walk_through')}
                >
                    ask PostHog AI to walk you through it
                </button>
                <span>.</span>
            </p>
        </>
    )
}

export function TodayBriefing(): JSX.Element {
    const {
        greeting,
        topReports,
        topReportsLoading,
        reportsFailed,
        reports,
        showPersonalBriefing,
        personalBriefing,
        briefingWaiting,
    } = useValues(todayLogic)
    const { loadTopReports, refreshBriefing } = useActions(todayLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const showFocus = showPersonalBriefing && !!featureFlags[FEATURE_FLAGS.TODAY_BRIEFING_FOCUS]

    return (
        <div className="TodayHome Today__page">
            <TodaySampleBanner />
            <TodayMetaLine />
            <section className="TodayHome__intro" aria-label="Daily brief">
                <div className="TodayHome__greeting">
                    <span>{greeting}</span>
                    {briefingWaiting ? (
                        <span className="TodayHome__badge" data-attr="today-briefing-writing">
                            <Spinner textColored />
                            <span>Writing your briefing…</span>
                        </span>
                    ) : showPersonalBriefing || personalBriefing?.status === 'failed' ? (
                        <LemonButton
                            size="xsmall"
                            icon={<IconRefresh />}
                            tooltip="Refresh briefing"
                            onClick={() => refreshBriefing()}
                            data-attr="today-briefing-refresh"
                        />
                    ) : null}
                </div>
                {showFocus && <TodayBriefingFocusLine />}
                {showPersonalBriefing ? (
                    <TodayPersonalBriefing />
                ) : topReports === null && reportsFailed ? (
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
