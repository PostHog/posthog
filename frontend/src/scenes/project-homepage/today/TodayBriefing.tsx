import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'
import { Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { urls } from 'scenes/urls'

import { TodayPreviewTrigger } from '~/layout/today/TodayPreviewTrigger'

import { WALK_THROUGH_QUESTION } from './todayAskPrompt'
import { TodayChipStack } from './TodayChipStack'
import { TodayIcon } from './TodayIcon'
import { todayLogic } from './todayLogic'
import { TodayPartyPopper } from './TodayPartyPopper'
import { TodayPersonalBriefing } from './TodayPersonalBriefing'
import { TodayRecents } from './TodayRecents'
import { TodaySampleBanner } from './TodaySampleBanner'
import { TodayBriefingSegment, reportIcon, reportSource } from './todaySignalReports'

const DATE_FORMAT = new Intl.DateTimeFormat(undefined, { weekday: 'short', day: 'numeric', month: 'short' })
const TIME_FORMAT = new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' })

function TodayMetaLine(): JSX.Element {
    const { now, currentTeam } = useValues(todayLogic)
    const date = new Date(now)
    return (
        <div className="TodayHome__meta">
            <TodayPartyPopper />
            <span className="whitespace-pre">{`${currentTeam?.name ?? 'Your project'} · ${DATE_FORMAT.format(date)} · `}</span>
            <time translate="no" dateTime={date.toISOString()}>
                {TIME_FORMAT.format(date)}
            </time>
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
        <LinkPrimitive
            to={urls.todayReport(reportId)}
            className="TodayInlineLink"
            data-active={hoveredReportId === reportId}
            data-state={reportStateOverrides[reportId] ?? 'open'}
            data-attr="today-briefing-report"
            onClick={() => report && reportOpened(report, 'briefing')}
            onMouseEnter={() => setHoveredReportId(reportId)}
            onMouseLeave={() => setHoveredReportId(null)}
        >
            {segment.text}
        </LinkPrimitive>
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
                        <LinkPrimitive to={urls.inbox()} className="TodayInboxLink" data-attr="today-briefing-inbox">
                            {`${moreReportCount} more for you in the Inbox`}
                        </LinkPrimitive>
                        <span>. </span>
                    </>
                )}
                <span>Or </span>
                <button
                    type="button"
                    className="TodayInlineAction"
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

    return (
        <div className="TodayHome Today__page" data-quill>
            <TodaySampleBanner />
            <TodayMetaLine />
            <section className="TodayHome__prose TodayHome__intro" aria-label="Daily brief">
                <div className="TodayHome__greeting">
                    <Text render={<h1 />} className="m-0 text-[21px] font-[560] tracking-[-0.015em]">
                        {greeting}
                    </Text>
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
                            <LinkPrimitive to={urls.inbox()} className="TodayInboxLink" data-attr="today-empty-inbox">
                                Open the Inbox
                            </LinkPrimitive>
                            <span> to see everything it’s tracking.</span>
                        </p>
                    </>
                ) : (
                    <TodayBriefingReports />
                )}
            </section>
            <TodayRecents />
        </div>
    )
}
