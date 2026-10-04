import { useActions } from 'kea'
import type { ReactNode } from 'react'

import { IconArrowRight, IconExternal, IconPlay, IconTrends } from '@posthog/icons'
import { Button, Text } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { urls } from 'scenes/urls'

import type { SignalViewApi } from 'products/today/frontend/generated/api.schemas'

import { signalDestination } from './todayEvidence'
import { TodayQuoteSegment, quoteSegments } from './todayFigures'
import { TodayFigureCardContent, anchorToday } from './todayFigureSources'
import { TodayIcon } from './TodayIcon'
import { TodayInlineTrend } from './TodayInlineTrend'
import { TodayPenMark } from './TodayPenMark'
import { shortDate } from './todayProse'
import { isSampleReportId } from './todaySampleReports'
import { TodayReportIcon, sourceStyle } from './todaySignalReports'
import { signalSourceLabel } from './todaySignalText'

const PEN_DELAY_MS = 180
const PEN_STAGGER_MS = 140

type QuotedContent = Extract<TodayFigureCardContent, { kind: 'signal' }>
type MetricContent = Extract<TodayFigureCardContent, { kind: 'metric' }>

interface QuoteSource {
    icon: TodayReportIcon
    label: string
    date: string
    signal: SignalViewApi
}

function quoteSource(content: QuotedContent): QuoteSource {
    return {
        icon: sourceStyle(content.signal.source_product).icon,
        label: signalSourceLabel(content.signal),
        date: content.signal.timestamp,
        signal: content.signal,
    }
}

function CardHeader({ icon, children }: { icon: ReactNode; children: ReactNode }): JSX.Element {
    return (
        <Text size="xs" variant="muted" render={<div />} className="flex items-center gap-1.5">
            {icon && (
                <span aria-hidden className="flex [&_svg]:size-3.5">
                    {icon}
                </span>
            )}
            {children}
        </Text>
    )
}

function CardDate({ date }: { date: string }): JSX.Element {
    const day = dayjs(date)
    return (
        <>
            <span aria-hidden>·</span>
            <time dateTime={date} title={day.format('LLL')}>
                {shortDate(day)}
            </time>
        </>
    )
}

function CardLink({
    to,
    external,
    dataAttr,
    children,
}: {
    to: string
    external: boolean
    dataAttr: string
    children: ReactNode
}): JSX.Element {
    return (
        <Button
            variant="link"
            size="sm"
            className="self-start px-0"
            nativeButton={false}
            render={<LinkPrimitive to={to} target={external ? '_blank' : undefined} />}
            data-attr={dataAttr}
        >
            {children}
            {external ? <IconExternal /> : <IconArrowRight />}
        </Button>
    )
}

function FullReportLink({ reportId, children }: { reportId: string; children: string }): JSX.Element | null {
    if (isSampleReportId(reportId)) {
        return null
    }
    return (
        <CardLink
            to={urls.inboxReport('reports', reportId)}
            external={false}
            dataAttr="today-report-figure-full-report"
        >
            {children}
        </CardLink>
    )
}

function SignalAction({ signal, reportId }: { signal: SignalViewApi; reportId: string }): JSX.Element | null {
    const { openSessionPlayer } = useActions(sessionPlayerModalLogic)
    const destination = signalDestination(signal)
    if (destination.kind === 'recording') {
        return (
            <Button
                variant="link"
                size="sm"
                className="self-start px-0"
                onClick={() => openSessionPlayer({ id: destination.sessionId }, destination.startAt)}
                data-attr="today-report-figure-play"
            >
                <IconPlay />
                {destination.offset ? `Play at ${destination.offset}` : 'Play recording'}
            </Button>
        )
    }
    if (destination.kind === 'link') {
        return (
            <CardLink to={destination.to} external={destination.external} dataAttr="today-report-figure-open">
                {destination.label}
            </CardLink>
        )
    }
    return <FullReportLink reportId={reportId}>Open the full report</FullReportLink>
}

function Quote({ segments }: { segments: TodayQuoteSegment[] }): JSX.Element {
    let order = 0
    return (
        <Text
            size="sm"
            render={<blockquote />}
            className="m-0 border-l-2 border-solid ps-3 text-pretty text-foreground"
        >
            {segments.map((segment, index) =>
                segment.marked ? (
                    <TodayPenMark key={index} seed={segment.text} delayMs={PEN_DELAY_MS + order++ * PEN_STAGGER_MS}>
                        {segment.text}
                    </TodayPenMark>
                ) : (
                    <span key={index}>{segment.text}</span>
                )
            )}
        </Text>
    )
}

function QuoteCard({
    content,
    figure,
    reportId,
}: {
    content: QuotedContent
    figure: string
    reportId: string
}): JSX.Element {
    const source = quoteSource(content)
    const { working } = content
    const segments = quoteSegments(content, figure).map((segment) =>
        source.date && !segment.marked ? { ...segment, text: anchorToday(segment.text, source.date) } : segment
    )
    return (
        <div className="flex flex-col gap-2 p-3">
            <CardHeader icon={<TodayIcon icon={source.icon} />}>
                <span>{source.label}</span>
                <CardDate date={source.date} />
            </CardHeader>
            <Quote segments={segments} />
            {working && (
                <Text size="xs" variant="muted" render={<p />} className="tabular-nums">
                    {`${working.expression} = `}
                    <span className="font-semibold text-foreground">{working.result}</span>
                </Text>
            )}
            <SignalAction signal={source.signal} reportId={reportId} />
        </div>
    )
}

function MetricCard({ content }: { content: MetricContent }): JSX.Element {
    return (
        <div className="flex flex-col gap-2 p-3">
            <CardHeader icon={<IconTrends />}>
                <span>Measured by an insight</span>
                {content.at && <CardDate date={content.at} />}
            </CardHeader>
            {content.caption && (
                <Text size="xs" variant="muted" render={<p />} className="text-pretty">
                    {content.caption}
                </Text>
            )}
            {content.trend && content.trend.length > 1 && (
                <div className="flex items-center gap-2 pt-4 pb-1 [&>span]:h-8 [&>span]:w-full [&>svg]:h-8 [&>svg]:w-full">
                    <TodayInlineTrend values={content.trend} type="bar" detailed partialLast={!!content.range} />
                </div>
            )}
            {content.range && (
                <Text size="xxs" variant="muted" render={<div />} className="-mt-1 flex justify-between">
                    <span>{content.range.from}</span>
                    <span>{content.range.to}</span>
                </Text>
            )}
            <Text size="xs" variant="muted" render={<p />} className="tabular-nums">
                <span className="font-semibold text-foreground">{content.total}</span>
                {content.window ? ` ${content.window}` : ''}
            </Text>
            {content.link && (
                <CardLink to={content.link.url} external dataAttr="today-report-figure-insight">
                    {content.link.label}
                </CardLink>
            )}
        </div>
    )
}

export function TodayFigureCard({
    content,
    figure,
    reportId,
}: {
    content: TodayFigureCardContent
    figure: string
    reportId: string
}): JSX.Element {
    if (content.kind === 'metric') {
        return <MetricCard content={content} />
    }
    if (content.kind === 'none') {
        return (
            <div className="flex flex-col gap-2 p-3">
                <CardHeader icon={null}>No source on this page</CardHeader>
                <FullReportLink reportId={reportId}>Read the full report</FullReportLink>
            </div>
        )
    }
    return <QuoteCard content={content} figure={figure} reportId={reportId} />
}
