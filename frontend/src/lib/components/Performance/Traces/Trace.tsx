import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { RefCallback, useEffect, useRef, useState } from 'react'
import clsx from 'clsx'
import {
    isInteractionNode,
    isQueryNode,
    isSessionNode,
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
    depth,
    start,
    duration,
    maxSpan,
}: Pick<SpanProps, 'depth' | 'duration' | 'start' | 'maxSpan'>): JSX.Element {
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
                    backgroundColor: getSeriesColor(depth),
                    width: `${durationWidth}%`,
                    marginLeft: `${startMargin}%`,
                }}
                className={'text-white pl-1'}
            >
                <span className={clsx(textIsOverflowing && 'invisible')}>{duration}ms</span>
            </div>
            <span
                className={clsx(!textIsOverflowing && 'hidden', 'text-black', startMargin > 50 ? 'absolute' : 'pl-1')}
                /* eslint-disable-next-line react/forbid-dom-props */
                style={{
                    right: `${101 - startMargin}%`,
                }}
            >
                {duration}ms
            </span>
        </div>
    )
}

function DescribeSpan({ node }: { node: TimeToSeeNode }): JSX.Element {
    const isFrustratingSession = isSessionNode(node) && node.data.frustrating_interactions_count > 0
    const hasIsFrustrating = isInteractionNode(node) || isQueryNode(node)
    const isFrustratingInteraction = hasIsFrustrating && !!node.data.is_frustrating
    return (
        <div className={clsx('flex flex-col')}>
            <div className={'flex flex-row items-center gap-2'}>
                {isSessionNode(node) ? 'session' : null}

                {(isFrustratingSession || isFrustratingInteraction) && (
                    <Tooltip title={'This was frustrating because it took longer than 5 seconds'}>
                        <IconSad />
                    </Tooltip>
                )}
            </div>
            {isInteractionNode(node) && (
                <>
                    {node.data.type}
                    {node.data.action && <> - {node.data.action}</>}
                </>
            )}
            {isQueryNode(node) && (
                <>
                    query
                    {node.data.query_type && <> - {node.data.query_type}</>}
                </>
            )}
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
    depth = 0,
}: SpanProps): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(false)

    return (
        <>
            <div className={clsx('w-full border px-4 py-4 flex flex-row justify-between', `Span__${type}`)}>
                <div className={'w-100 relative flex flex-row gap-2'}>
                    <LemonButton
                        noPadding
                        status="stealth"
                        onClick={() => setIsExpanded(!isExpanded)}
                        icon={isExpanded ? <IconUnfoldLess /> : <IconUnfoldMore />}
                        title={isExpanded ? 'Collapse span' : 'Expand span'}
                    />

                    {data && <DescribeSpan node={data} />}
                </div>
                <div
                    ref={widthTrackingRef}
                    className={'grow self-center'}
                    /* eslint-disable-next-line react/forbid-dom-props */
                    style={{
                        width: durationContainerWidth || '100%',
                        maxWidth: durationContainerWidth,
                        minWidth: durationContainerWidth,
                    }}
                >
                    <TraceBar maxSpan={maxSpan} duration={duration} start={start} depth={depth} />
                </div>
            </div>
            {isExpanded && (
                <>
                    <NodeFacts node={data} />
                    <div className={'pl-4'}>
                        {children.map((child, index) => (
                            <Span
                                key={`${depth}-${index}`}
                                maxSpan={maxSpan}
                                durationContainerWidth={durationContainerWidth}
                                widthTrackingRef={widthTrackingRef}
                                {...child}
                            />
                        ))}
                    </div>
                </>
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
    data: TimeToSeeNode
    depth?: number
    children: SpanData[]
}

interface ProcessSpans {
    spans: SpanData[]
    maxDuration: number
}

function NodeFacts({ node }: { node: TimeToSeeNode }): JSX.Element {
    const facts = {
        type: isInteractionNode(node) ? `${node.data.action ?? 'load'} in ${node.data.context}` : 'ClickHouse query',
        context: isInteractionNode(node) ? node.data.context : undefined,
        action: isInteractionNode(node) ? node.data.action : undefined,
        page: isInteractionNode(node) ? node.data.current_url : undefined,
        cacheHitRatio: isInteractionNode(node)
            ? `${Math.round((node.data.insights_fetched_cached / node.data.insights_fetched) * 100)}%`
            : undefined,
        duration: getDurationMs(node),
    }

    return (
        <div className={clsx('w-full border px-4 py-4 flex flex-col justify-between')}>
            {Object.entries(facts)
                .filter((entry) => entry[1] !== undefined && entry[1] !== '')
                .map(([key, fact], index) => {
                    return (
                        <div key={index} className={'flex flex-row w-full overflow-scroll whitespace-nowrap'}>
                            <strong>{key}: </strong>
                            <span>{fact}</span>
                        </div>
                    )
                })}
        </div>
    )
}

function getDurationMs(node: TimeToSeeNode): number {
    switch (node.type) {
        case 'session':
            return node.data.duration_ms
        case 'interaction':
        case 'event':
            return node.data.time_to_see_data_ms
        case 'query':
        case 'subquery':
            return node.data.query_duration_ms
    }
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
        const duration = getDurationMs(node)
        spanData.push({
            type: node.type,
            start: start,
            duration: duration,
            data: node,
            depth: level,
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
        duration: getDurationMs(timeToSeeSession),
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
