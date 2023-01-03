import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { RefCallback, useEffect, useRef, useState } from 'react'
import clsx from 'clsx'
import {
    isInteractionNode,
    TimeToSeeInteractionNode,
    TimeToSeeNode,
    TimeToSeeQueryNode,
    TimeToSeeSessionNode,
} from '~/queries/nodes/TimeToSeeData/types'
import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyDuration } from 'lib/utils'
import { dayjs } from 'lib/dayjs'
import { IconSad, IconUnfoldLess, IconUnfoldMore } from 'lib/components/icons'
import { getSeriesColor } from 'lib/colors'
import { LemonButton } from 'lib/components/LemonButton'
import { Tooltip } from 'lib/components/Tooltip'

export interface SpanProps extends SpanData {
    maxSpan: number
    durationContainerWidth: number | undefined
    widthTrackingRef?: RefCallback<HTMLElement>
}

const checkOverflow = (textContainer: HTMLSpanElement | null): boolean => {
    if (textContainer) {
        return (
            textContainer.offsetHeight < textContainer.scrollHeight ||
            textContainer.offsetWidth < textContainer.scrollWidth
        )
    }
    return false
}

function TraceBar({
    level,
    start,
    duration,
    maxSpan,
}: Pick<SpanProps, 'level' | 'duration' | 'start' | 'maxSpan'>): JSX.Element {
    const durationWidth = (duration / maxSpan) * 100
    const startMargin = (start / maxSpan) * 100
    const [textIsOverflowing, setTextIsOverflowing] = useState<boolean>(false)
    const overflowingText = useRef<HTMLDivElement | null>(null)

    useEffect(() => {
        if (checkOverflow(overflowingText.current)) {
            setTextIsOverflowing(true)
            return
        }

        setTextIsOverflowing(false)
    }, [duration, start, maxSpan])

    return (
        <div className={clsx('h-full flex relative', startMargin > 50 ? 'flex-row-reverse' : 'flex-row')}>
            <div
                ref={overflowingText}
                /* eslint-disable-next-line react/forbid-dom-props */
                style={{
                    backgroundColor: getSeriesColor(level),
                    width: `${durationWidth}%`,
                    marginLeft: `${startMargin}%`,
                }}
                className={'text-white pl-1'}
            >
                <span className={clsx(textIsOverflowing && 'invisible')}>{duration}ms</span>
            </div>
            <span
                className={clsx(!textIsOverflowing && 'hidden', 'text-black', startMargin > 50 ? 'absolute' : 'pl-1')}
                style={{
                    right: `${101 - startMargin}%`,
                }}
            >
                {duration}ms
            </span>
        </div>
    )
}

export function Span({
    start,
    duration,
    data,
    maxSpan,
    durationContainerWidth,
    widthTrackingRef,
    type,
    children,
    level = 0,
}: SpanProps): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(false)

    return (
        <>
            <div className={clsx('w-full border px-4 py-4 flex flex-row justify-between', `Span__${type}`)}>
                <div className={'w-100 relative flex flex-row gap-2'}>
                    {children.length ? (
                        <LemonButton
                            noPadding
                            status="stealth"
                            onClick={() => setIsExpanded(!isExpanded)}
                            icon={isExpanded ? <IconUnfoldLess /> : <IconUnfoldMore />}
                            title={isExpanded ? 'Collapse span' : 'Expand span'}
                        />
                    ) : null}
                    <div className={clsx('flex flex-col')}>
                        <div className={'flex flex-row items-center gap-2'}>
                            {data && 'type' in data ? data?.type : 'session'}{' '}
                            {data && 'data' in data && 'is_frustrating' in data.data && !!data.data.is_frustrating && (
                                <Tooltip title={'This was frustrating - because it took longer than 5 seconds'}>
                                    <IconSad />
                                </Tooltip>
                            )}
                        </div>
                        {data && 'data' in data && 'type' in data.data && 'action' in data.data && (
                            <>
                                {data.data.type} - {data.data.action}
                            </>
                        )}
                    </div>
                </div>
                <div
                    ref={widthTrackingRef}
                    className={'grow self-center'}
                    style={{
                        width: durationContainerWidth || '100%',
                        maxWidth: durationContainerWidth,
                        minWidth: durationContainerWidth,
                    }}
                >
                    <TraceBar maxSpan={maxSpan} duration={duration} start={start} level={level} />
                </div>
            </div>
            {isExpanded && (
                <div className={'pl-4'}>
                    {children.map((child, index) => (
                        <Span
                            key={`${level}-${index}`}
                            maxSpan={maxSpan}
                            durationContainerWidth={durationContainerWidth}
                            widthTrackingRef={widthTrackingRef}
                            {...child}
                        />
                    ))}
                </div>
            )}
        </>
    )
}

export interface TraceProps {
    timeToSeeSession: TimeToSeeSessionNode
}

interface SpanData {
    type: 'session' | 'interaction' | 'event' | 'query' | 'subquery'
    start: number // milliseconds after session start
    duration: number
    data?: TimeToSeeNode
    level?: number
    children: SpanData[]
}

interface ProcessSpans {
    spans: SpanData[]
    maxDuration: number
}

function walkSpans(
    nodes: Array<TimeToSeeInteractionNode | TimeToSeeQueryNode>,
    sessionStart: dayjs.Dayjs,
    level: number = 1
): ProcessSpans {
    const spanData: SpanData[] = []
    let maxDuration = 0

    nodes.forEach((node) => {
        const walkedChildren = walkSpans(node.children, sessionStart, level++)

        const start = dayjs(node.data.timestamp).diff(sessionStart)
        const duration = isInteractionNode(node) ? node.data.time_to_see_data_ms : node.data.query_duration_ms
        spanData.push({
            type: node.type,
            start: start,
            duration: duration,
            data: node,
            level,
            children: walkedChildren.spans,
        })
        maxDuration = start + duration

        maxDuration = Math.max(maxDuration, walkedChildren.maxDuration)
    })

    return { spans: spanData, maxDuration }
}

function flattenSpans(timeToSeeSession: TimeToSeeSessionNode): ProcessSpans {
    const walkedChildren = walkSpans(timeToSeeSession.children, dayjs(timeToSeeSession.data.session_start))
    walkedChildren.spans.unshift({
        type: 'session',
        start: 0,
        duration: timeToSeeSession.data.duration_ms,
        data: timeToSeeSession,
        children: [], // the session's children are shown separately
    })

    return {
        spans: walkedChildren.spans,
        maxDuration: Math.max(timeToSeeSession.data.duration_ms, walkedChildren.maxDuration),
    }
}

export function Trace({ timeToSeeSession }: TraceProps): JSX.Element {
    const { ref: parentSpanRef, width: parentSpanWidth } = useResizeObserver()

    const { spans, maxDuration } = flattenSpans(timeToSeeSession)
    return (
        <div className={'flex flex-col gap-1 border rounded p-4'}>
            <h2>{timeToSeeSession.data.session_id}</h2>
            <div>
                session length: {humanFriendlyDuration(timeToSeeSession.data.total_interaction_time_to_see_data_ms)}
            </div>
            <div>
                session start: <TZLabel time={timeToSeeSession.data.session_start} />
            </div>
            {spans.map((spanData, i) => {
                let ref = undefined
                if (spanData.type === 'session') {
                    ref = parentSpanRef
                }
                return (
                    <div key={i}>
                        <Span
                            widthTrackingRef={ref}
                            // don't set duration container width back onto the element that is generating it
                            durationContainerWidth={!!ref ? undefined : parentSpanWidth}
                            maxSpan={maxDuration}
                            {...spanData}
                        />
                    </div>
                )
            })}
        </div>
    )
}
