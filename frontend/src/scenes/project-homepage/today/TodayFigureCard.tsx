import { useActions } from 'kea'
import type { ReactNode } from 'react'

import { IconArrowRight, IconExternal, IconPlay, IconTrends } from '@posthog/icons'
import { Button, Text } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { urls } from 'scenes/urls'

import type { SignalNodeApi } from 'products/signals/frontend/generated/api.schemas'

import { TodayIcon } from './TodayIcon'
import { TodayInlineTrend } from './TodayInlineTrend'
import { TodayPenStroke } from './TodayPenStroke'
import {
    TodayFigureCardContent,
    anchorToday,
    highlightSegments,
    scoutLabel,
    signalDestination,
} from './todayReportPresentation'
import { sourceStyle } from './todaySignalReports'

const PLAYER_LEAD_IN_MS = 5000

const PEN_DELAY_MS = 180
const PEN_STAGGER_MS = 140

function Penned({ children, order }: { children: string; order: number }): JSX.Element {
    return (
        <span className="TodayPenned text-[var(--foreground)]">
            {children}
            <TodayPenStroke seed={children} delayMs={PEN_DELAY_MS + order * PEN_STAGGER_MS} />
        </span>
    )
}

function Quote({ text, values }: { text: string; values: string[] }): JSX.Element {
    let order = 0
    return (
        <Text
            size="sm"
            render={<blockquote />}
            className="m-0 border-l-2 border-solid ps-3 text-pretty text-[var(--foreground)]"
        >
            {highlightSegments(text, values).map((segment, index) =>
                segment.marked ? (
                    <Penned key={index} order={order++}>
                        {segment.text}
                    </Penned>
                ) : (
                    <span key={index}>{segment.text}</span>
                )
            )}
        </Text>
    )
}

function Sum({ parts, figure }: { parts: string[]; figure: string }): JSX.Element {
    return (
        <Text size="xs" variant="muted" render={<p />} className="tabular-nums">
            {parts.join(' + ')} = <span className="font-semibold text-[var(--foreground)]">{figure}</span>
        </Text>
    )
}

function SourceDate({ date }: { date: string }): JSX.Element {
    const day = dayjs(date)
    return (
        <time dateTime={date} title={day.format('LLL')}>
            {day.format('D MMM')}
        </time>
    )
}

function Rounded({ exact, figure }: { exact: string; figure: string }): JSX.Element {
    return (
        <Text size="xs" variant="muted" render={<p />} className="tabular-nums">
            {exact} ≈ <span className="font-semibold text-[var(--foreground)]">{figure}</span>
        </Text>
    )
}

function signalLabel(signal: SignalNodeApi): string {
    const source = sourceStyle(signal.source_product)
    const skill = (signal.extra as { skill_name?: unknown } | null)?.skill_name
    return signal.source_product === 'signals_scout'
        ? (scoutLabel(typeof skill === 'string' ? skill : null) ?? source.label)
        : source.label
}

function Header({ icon, children }: { icon?: ReactNode; children: ReactNode }): JSX.Element {
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

function SignalAction({ signal }: { signal: SignalNodeApi }): JSX.Element | null {
    const { openSessionPlayer } = useActions(sessionPlayerModalLogic)
    const destination = signalDestination(signal)
    if (destination.kind === 'recording') {
        return (
            <Button
                variant="link"
                size="sm"
                className="self-start px-0"
                onClick={() =>
                    openSessionPlayer(
                        { id: destination.sessionId },
                        destination.timestamp ? Math.max(destination.timestamp - PLAYER_LEAD_IN_MS, 0) : null
                    )
                }
                data-attr="today-report-figure-play"
            >
                <IconPlay />
                {destination.offset ? `Play at ${destination.offset}` : 'Play recording'}
            </Button>
        )
    }
    if (destination.kind === 'link') {
        return (
            <Button
                variant="link"
                size="sm"
                className="self-start px-0"
                nativeButton={false}
                render={<LinkPrimitive to={destination.to} target={destination.external ? '_blank' : undefined} />}
                data-attr="today-report-figure-open"
            >
                {destination.label}
                <IconExternal />
            </Button>
        )
    }
    return null
}

function FullReportLink({ reportId, label }: { reportId: string; label: string }): JSX.Element {
    return (
        <Button
            variant="link"
            size="sm"
            className="self-start px-0"
            nativeButton={false}
            render={<LinkPrimitive to={urls.inboxReport('reports', reportId)} />}
            data-attr="today-report-figure-full-report"
        >
            {label}
            <IconArrowRight />
        </Button>
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
    if (content.kind === 'signal') {
        return (
            <div className="flex flex-col gap-2 p-3">
                <Header icon={<TodayIcon icon={sourceStyle(content.signal.source_product).icon} />}>
                    <span>{signalLabel(content.signal)}</span>
                    <span aria-hidden>·</span>
                    <SourceDate date={content.signal.timestamp} />
                </Header>
                <Quote
                    text={anchorToday(content.excerpt, content.signal.timestamp)}
                    values={content.values ?? [figure]}
                />
                {content.parts && <Sum parts={content.parts} figure={figure} />}
                {content.exact && <Rounded exact={content.exact} figure={figure} />}
                {content.working && (
                    <Text size="xs" variant="muted" render={<p />} className="tabular-nums">
                        {content.working.expression} ={' '}
                        <span className="font-semibold text-[var(--foreground)]">{content.working.result}</span>
                    </Text>
                )}
                {signalDestination(content.signal).kind !== 'read' ? (
                    <SignalAction signal={content.signal} />
                ) : (
                    <FullReportLink reportId={reportId} label="Open the full report" />
                )}
            </div>
        )
    }
    if (content.kind === 'research') {
        return (
            <div className="flex flex-col gap-2 p-3">
                <Header icon={<TodayIcon icon="scout" />}>
                    <span>Agent’s research</span>
                    <span aria-hidden>·</span>
                    <SourceDate date={content.note.at} />
                </Header>
                <Quote text={anchorToday(content.excerpt, content.note.at)} values={content.values ?? [figure]} />
                {content.parts && <Sum parts={content.parts} figure={figure} />}
                {content.exact && <Rounded exact={content.exact} figure={figure} />}
                {content.signal && signalDestination(content.signal).kind !== 'read' ? (
                    <SignalAction signal={content.signal} />
                ) : (
                    <FullReportLink reportId={reportId} label="Open the full report" />
                )}
            </div>
        )
    }
    if (content.kind === 'report') {
        return (
            <div className="flex flex-col gap-2 p-3">
                <Header>Later in the report</Header>
                <Quote text={content.excerpt} values={content.values ?? [figure]} />
                {content.parts && <Sum parts={content.parts} figure={figure} />}
                {content.exact && <Rounded exact={content.exact} figure={figure} />}
                <FullReportLink reportId={reportId} label="Open the full report" />
            </div>
        )
    }
    if (content.kind === 'metric') {
        return (
            <div className="flex flex-col gap-2 p-3">
                <Header icon={<IconTrends />}>
                    <span>Measured by a saved query</span>
                    {content.at && (
                        <>
                            <span aria-hidden>·</span>
                            <SourceDate date={content.at} />
                        </>
                    )}
                </Header>
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
                    <span className="font-semibold text-[var(--foreground)]">{content.total}</span>
                    {content.window ? ` ${content.window}` : ''}
                </Text>
                {content.link && (
                    <Button
                        variant="link"
                        size="sm"
                        className="self-start px-0"
                        nativeButton={false}
                        render={<LinkPrimitive to={content.link.url} target="_blank" />}
                        data-attr="today-report-figure-insight"
                    >
                        {content.link.label}
                        <IconExternal />
                    </Button>
                )}
            </div>
        )
    }
    return (
        <div className="flex flex-col gap-2 p-3">
            <Header>No source on this page</Header>
            <FullReportLink reportId={reportId} label="Read the full report" />
        </div>
    )
}
