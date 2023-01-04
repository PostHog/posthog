import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { RefCallback, useEffect, useRef, useState } from 'react'
import clsx from 'clsx'
import {
    isInteractionNode,
    isQueryNode,
    isSessionNode,
    TimeToSeeNode,
    TimeToSeeSessionNode,
} from '~/queries/nodes/TimeToSeeData/types'
import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyDuration } from 'lib/utils'
import { IconSad, IconUnfoldLess, IconUnfoldMore } from 'lib/components/icons'
import { getSeriesColor } from 'lib/colors'
import { LemonButton } from 'lib/components/LemonButton'
import { Tooltip } from 'lib/components/Tooltip'
import { getDurationMs, SpanData, traceLogic } from '~/queries/nodes/TimeToSeeData/Trace/traceLogic'
import { useActions, useValues } from 'kea'

export interface SpanProps {
    maxSpan: number
    durationContainerWidth: number | undefined
    spanData: SpanData
    widthTrackingRef?: RefCallback<HTMLElement>
    isExpandable?: boolean
    onClick?: (span: SpanData) => void
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

function TraceBar({ spanData, maxSpan }: SpanProps): JSX.Element {
    const [durationWidth, setDurationWidth] = useState<number>(0)
    const [startMargin, setStartMargin] = useState<number>(0)

    const [textIsOverflowing, setTextIsOverflowing] = useState<boolean>(false)
    const overflowingText = useRef<HTMLDivElement | null>(null)

    useEffect(() => {
        setTextIsOverflowing(checkOverflow(overflowingText.current))
        const nextDurationWidth = (spanData.duration / maxSpan) * 100
        const nextStartMargin = (spanData.start / maxSpan) * 100
        if (nextDurationWidth != durationWidth) {
            console.log('setting duration width to ', nextDurationWidth, ' with max span of ', maxSpan)
            setDurationWidth(nextDurationWidth)
        }
        if (nextStartMargin !== startMargin) {
            setStartMargin(nextStartMargin)
        }
    }, [spanData, maxSpan])

    return (
        <div className={clsx('h-full flex relative', startMargin > 50 ? 'flex-row-reverse' : 'flex-row')}>
            <div
                ref={overflowingText}
                /* eslint-disable-next-line react/forbid-dom-props */
                style={{
                    backgroundColor: getSeriesColor(spanData.depth),
                    width: `${durationWidth}%`,
                    marginLeft: `${startMargin}%`,
                }}
                className={'text-white pl-1'}
            >
                <span className={clsx(textIsOverflowing && 'invisible')}>{spanData.duration}ms</span>
            </div>
            <span
                className={clsx(!textIsOverflowing && 'hidden', 'text-black', startMargin > 50 ? 'absolute' : 'pl-1')}
                /* eslint-disable-next-line react/forbid-dom-props */
                style={{
                    right: `${101 - startMargin}%`,
                }}
            >
                {spanData.duration}ms
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
    maxSpan,
    durationContainerWidth,
    spanData,
    widthTrackingRef,
    isExpandable,
    onClick,
}: SpanProps): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(isExpandable)

    const onClickProps = spanData.data.type === 'interaction' ? { onClick: () => onClick?.(spanData) } : undefined
    return (
        <>
            <div
                className={clsx(
                    'w-full border px-4 py-4 flex flex-row justify-between',
                    `Span__${spanData.type}`,
                    !!onClick && 'cursor-pointer'
                )}
                {...onClickProps}
            >
                <div className={'w-100 relative flex flex-row gap-2'}>
                    {isExpandable && (
                        <LemonButton
                            noPadding
                            status="stealth"
                            onClick={() => setIsExpanded(!isExpanded)}
                            icon={isExpanded ? <IconUnfoldLess /> : <IconUnfoldMore />}
                            title={isExpanded ? 'Collapse span' : 'Expand span'}
                        />
                    )}

                    {spanData.data && <DescribeSpan node={spanData.data} />}
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
                    <TraceBar maxSpan={maxSpan} durationContainerWidth={durationContainerWidth} spanData={spanData} />
                </div>
            </div>
            {isExpanded && (
                <>
                    <NodeFacts
                        facts={{
                            ...sessionNodeFacts(spanData.data),
                            ...interactionNodeFacts(spanData.data),
                            ...queryNodeFacts(spanData.data),
                            duration: `${getDurationMs(spanData.data)}ms`,
                        }}
                    />
                    <div className={'pl-4'}>
                        {spanData.children.map((child, index) => (
                            <Span
                                key={`${spanData.depth}-${index}`}
                                maxSpan={maxSpan}
                                durationContainerWidth={durationContainerWidth}
                                widthTrackingRef={undefined}
                                spanData={child}
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

function interactionNodeFacts(node: TimeToSeeNode): Record<string, any> {
    return isInteractionNode(node)
        ? {
              type: `${node.data.action || 'load'} in ${node.data.context}`,
              context: node.data.context,
              action: node.data.action,
              page: node.data.current_url,
              cacheHitRatio: `${Math.round((node.data.insights_fetched_cached / node.data.insights_fetched) * 100)}%`,
          }
        : {}
}

function sessionNodeFacts(node: TimeToSeeNode): Record<string, any> {
    return isSessionNode(node) ? { type: 'session' } : {}
}

function queryNodeFacts(node: TimeToSeeNode): Record<string, any> {
    return isQueryNode(node) ? { type: 'Clickhouse query', hasJoins: !!node.data.has_joins ? 'true' : 'false' } : {}
}

function NodeFacts({ facts }: { facts: Record<string, any> }): JSX.Element {
    return (
        <div className={clsx('w-full border px-4 py-4 flex flex-col justify-between')}>
            {Object.entries(facts)
                .filter((entry) => entry[1] !== undefined && entry[1] !== '')
                .map(([key, fact], index) => {
                    return (
                        <div key={index} className={'flex flex-row w-full overflow-auto whitespace-nowrap'}>
                            <strong>{key}:</strong> <span>{fact}</span>
                        </div>
                    )
                })}
        </div>
    )
}

function TraceOverview({
    timeToSeeSession,
    processedSpans,
    onClick,
}: {
    processedSpans: SpanData[]
    timeToSeeSession: TimeToSeeSessionNode
    onClick: (span: SpanData) => void
}): JSX.Element {
    const { ref: parentSpanRef, width: parentSpanWidth } = useResizeObserver()

    return (
        <>
            <div className={'flex flex-col gap-1 border rounded p-4'}>
                <h1>Session Interactions</h1>
                <NodeFacts facts={sessionNodeFacts(timeToSeeSession)} />
                {processedSpans
                    .filter((spanData) => ['interaction', 'session'].includes(spanData.type))
                    .map((spanData, i) => {
                        let ref = undefined
                        if (spanData.type === 'session') {
                            ref = parentSpanRef
                        }
                        return (
                            <div key={i}>
                                <Span
                                    onClick={onClick}
                                    isExpandable={false}
                                    widthTrackingRef={ref}
                                    // don't set duration container width back onto the element that is generating it
                                    durationContainerWidth={!!ref ? undefined : parentSpanWidth}
                                    maxSpan={timeToSeeSession.data.duration_ms}
                                    spanData={spanData}
                                />
                            </div>
                        )
                    })}
            </div>
        </>
    )
}

export function Trace({ timeToSeeSession }: TraceProps): JSX.Element {
    const { ref: selectedSpanRef, width: selectedSpanWidth } = useResizeObserver()

    const logic = traceLogic({ sessionNode: timeToSeeSession })
    const { focussedInteraction, processedSpans } = useValues(logic)
    const { showInteractionTrace } = useActions(logic)

    return (
        <div className={'flex flex-col gap-1 border rounded p-4'}>
            <h2>{timeToSeeSession.data.session_id}</h2>
            <div>
                session length: {humanFriendlyDuration(timeToSeeSession.data.total_interaction_time_to_see_data_ms)}
            </div>
            <div>
                session start: <TZLabel time={timeToSeeSession.data.session_start} />
            </div>
            <TraceOverview
                processedSpans={processedSpans}
                timeToSeeSession={timeToSeeSession}
                onClick={(span) => showInteractionTrace(span)}
            />

            {focussedInteraction ? (
                <Span
                    isExpandable={true}
                    widthTrackingRef={selectedSpanRef}
                    // don't set duration container width back onto the element that is generating it
                    durationContainerWidth={selectedSpanWidth}
                    // the selected span _must_ always have a larger duration than its children
                    maxSpan={focussedInteraction.duration}
                    spanData={focussedInteraction}
                />
            ) : null}
        </div>
    )
}
