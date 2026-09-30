import { useActions, useValues } from 'kea'

import {
    Avatar,
    AvatarFallback,
    AvatarGroup,
    Button,
    Heading,
    Highlight,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemTitle,
    Text,
    cn,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { urls } from 'scenes/urls'

import { TodayAskBox } from './TodayAskBox'
import { TodayIcon } from './TodayIcon'
import { todayLogic } from './todayLogic'
import { TodaySampleBanner } from './TodaySampleBanner'
import { TodayBriefingSegment, reportIcon } from './todaySignalReports'

const DATE_FORMAT = new Intl.DateTimeFormat(undefined, { weekday: 'short', day: 'numeric', month: 'short' })
const TIME_FORMAT = new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' })

// Quill has no inline text link, so a router link in running text takes the underline from tokens.
const INLINE_LINK = 'underline underline-offset-4 hover:text-foreground'

function TodayMetaLine(): JSX.Element {
    const { now, currentTeam } = useValues(todayLogic)
    const date = new Date(now)
    return (
        <Text size="xs" variant="muted" className="font-mono">
            <span>{`${currentTeam?.name ?? 'Your project'} · ${DATE_FORMAT.format(date)} · `}</span>
            <time translate="no" className="tabular-nums text-foreground">
                {TIME_FORMAT.format(date)}
            </time>
        </Text>
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
        <LinkPrimitive
            to={urls.todayReport(reportId)}
            className={cn(INLINE_LINK, hoveredReportId === reportId && 'text-foreground')}
            data-attr="today-briefing-report"
            onClick={() => report && reportOpened(report, 'briefing')}
            onMouseEnter={() => setHoveredReportId(reportId)}
            onMouseLeave={() => setHoveredReportId(null)}
        >
            {segment.text}
        </LinkPrimitive>
    )
    return segment.highlight ? <Highlight>{link}</Highlight> : link
}

function TodayBriefingReports(): JSX.Element {
    const { reportSummary, reports, briefing, moreReportCount } = useValues(todayLogic)
    const { openReport, setHoveredReportId } = useActions(todayLogic)
    const { askSidePanelMax } = useActions(maxGlobalLogic)

    return (
        <>
            <div className="flex flex-wrap items-center gap-3">
                <Text size="lg" weight="medium">
                    {reportSummary}
                </Text>
                <AvatarGroup stacked size="sm">
                    {reports.map((report) => (
                        <Avatar
                            key={report.id}
                            render={
                                <button
                                    type="button"
                                    aria-label={`Open ${report.title ?? 'report'}`}
                                    data-attr="today-briefing-chip"
                                    onClick={() => openReport(report, 'chip')}
                                    onMouseEnter={() => setHoveredReportId(report.id)}
                                    onMouseLeave={() => setHoveredReportId(null)}
                                />
                            }
                        >
                            <AvatarFallback>
                                <TodayIcon icon={reportIcon(report)} />
                            </AvatarFallback>
                        </Avatar>
                    ))}
                </AvatarGroup>
            </div>
            {briefing.map((paragraph, index) => (
                <Text key={index} size="lg" variant="muted">
                    {paragraph.map((segment, segmentIndex) => (
                        <BriefingSegment key={segmentIndex} segment={segment} />
                    ))}
                </Text>
            ))}
            <div className="flex flex-wrap items-center gap-2">
                {moreReportCount > 0 && (
                    <Button
                        variant="link-muted"
                        render={<LinkPrimitive to={urls.inbox()} />}
                        data-attr="today-briefing-inbox"
                    >
                        {`${moreReportCount} more ${moreReportCount === 1 ? 'report is' : 'reports are'} in the Inbox`}
                    </Button>
                )}
                <Button
                    variant="link"
                    data-attr="today-ask-about-edition"
                    onClick={() => askSidePanelMax('Walk me through what changed in my product today.')}
                >
                    Ask PostHog AI to walk you through it
                </Button>
            </div>
        </>
    )
}

export function TodayBriefing(): JSX.Element {
    const { greeting, topReports, topReportsLoading, reportsFailed, reports } = useValues(todayLogic)
    const { loadTopReports } = useActions(todayLogic)

    return (
        <>
            <TodaySampleBanner />
            <TodayMetaLine />
            <section className="flex flex-col gap-3" aria-label="Daily brief">
                <Heading size="xl" render={<h1 />}>
                    {greeting}
                </Heading>
                {topReports === null && reportsFailed ? (
                    <Item variant="outline" tone="destructive" role="alert">
                        <ItemContent>
                            <ItemTitle>Couldn’t load your reports</ItemTitle>
                            <ItemDescription>Try again, or open the Inbox to see them there.</ItemDescription>
                        </ItemContent>
                        <ItemActions>
                            <Button
                                variant="outline"
                                size="sm"
                                loading={topReportsLoading}
                                onClick={() => loadTopReports()}
                                data-attr="today-reports-retry"
                            >
                                Try again
                            </Button>
                        </ItemActions>
                    </Item>
                ) : topReports === null ? (
                    <Text size="lg" variant="muted" className="quill-shimmer">
                        Reading what changed in your project…
                    </Text>
                ) : reports.length === 0 ? (
                    <>
                        <Text size="lg" weight="medium">
                            Nothing needs your attention
                        </Text>
                        <Text size="lg" variant="muted">
                            Self-driving turns signals from across PostHog into reports worth acting on. New ones show
                            up here as it finds them.{' '}
                            <LinkPrimitive to={urls.inbox()} className={INLINE_LINK} data-attr="today-empty-inbox">
                                Open the Inbox
                            </LinkPrimitive>{' '}
                            to see everything it’s tracking.
                        </Text>
                    </>
                ) : (
                    <TodayBriefingReports />
                )}
            </section>
            <TodayAskBox />
        </>
    )
}
