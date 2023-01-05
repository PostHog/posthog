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
import { sessionNodeFacts, SpanData, traceLogic } from '~/queries/nodes/TimeToSeeData/Trace/traceLogic'
import { BindLogic, useActions, useValues } from 'kea'

export interface SpanProps {
    maxSpan: number
    durationContainerWidth: number | undefined
    spanData: SpanData
    widthTrackingRef?: RefCallback<HTMLElement>
    onClick: (s: SpanData) => void
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

function SpanBar({ spanData, maxSpan }: Pick<SpanProps, 'spanData' | 'maxSpan'>): JSX.Element {
    const [durationWidth, setDurationWidth] = useState<number>(0)
    const [startMargin, setStartMargin] = useState<number>(0)

    const [textIsOverflowing, setTextIsOverflowing] = useState<boolean>(false)
    const overflowingText = useRef<HTMLDivElement | null>(null)

    useEffect(() => {
        setTextIsOverflowing(checkOverflow(overflowingText.current))
        const nextDurationWidth = (spanData.duration / maxSpan) * 100
        const nextStartMargin = (spanData.start / maxSpan) * 100
        if (nextDurationWidth != durationWidth) {
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

function SpanBarWrapper(props: {
    ref: RefCallback<HTMLElement> | undefined
    durationContainerWidth: number | undefined
    maxSpan: number
    spanData: SpanData
}): JSX.Element {
    return (
        <div
            ref={props.ref}
            className={'grow self-center'}
            /* eslint-disable-next-line react/forbid-dom-props */
            style={{
                width: props.durationContainerWidth || '100%',
                maxWidth: props.durationContainerWidth,
                minWidth: props.durationContainerWidth,
            }}
        >
            <SpanBar maxSpan={props.maxSpan} spanData={props.spanData} />
        </div>
    )
}

export function ExpandableSpan({
    maxSpan,
    durationContainerWidth,
    spanData,
    widthTrackingRef,
    onClick,
}: SpanProps): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(true)

    const { focussedNode } = useValues(traceLogic)
    const styleProps =
        focussedNode?.id === spanData.id
            ? {
                  style: { borderColor: getSeriesColor(spanData.depth) },
              }
            : {}

    return (
        <>
            <div
                className={clsx('w-full border px-4 py-4 flex flex-row justify-between', `Span__${spanData.type}`)}
                {...styleProps}
                onClick={() => onClick(spanData)}
            >
                <div className={'w-100 relative flex flex-row gap-2'}>
                    <LemonButton
                        noPadding
                        status="stealth"
                        onClick={() => setIsExpanded(!isExpanded)}
                        icon={isExpanded ? <IconUnfoldLess /> : <IconUnfoldMore />}
                        title={isExpanded ? 'Collapse span' : 'Expand span'}
                    />

                    {spanData.data && <DescribeSpan node={spanData.data} />}
                </div>
                <SpanBarWrapper
                    ref={widthTrackingRef}
                    durationContainerWidth={durationContainerWidth}
                    maxSpan={maxSpan}
                    spanData={spanData}
                />
            </div>
            {isExpanded && (
                <div className={'pl-4'}>
                    {spanData.children.map((child, index) => (
                        <ExpandableSpan
                            onClick={onClick}
                            key={`${spanData.depth}-${index}`}
                            maxSpan={maxSpan}
                            durationContainerWidth={durationContainerWidth}
                            widthTrackingRef={undefined}
                            spanData={child}
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

    const { focussedInteraction } = useValues(traceLogic)

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

                        const onClickProps =
                            spanData.data.type === 'interaction'
                                ? {
                                      onClick: () => {
                                          return onClick?.(spanData)
                                      },
                                  }
                                : undefined

                        const styleProps =
                            focussedInteraction?.id === spanData.id
                                ? {
                                      style: { borderColor: getSeriesColor(spanData.depth) },
                                  }
                                : {}

                        return (
                            <div key={i}>
                                <div
                                    className={clsx(
                                        'w-full border px-4 py-4 flex flex-row justify-between',
                                        `Span__${spanData.type}`,
                                        spanData.type === 'interaction' && 'cursor-pointer'
                                    )}
                                    {...onClickProps}
                                    {...styleProps}
                                >
                                    <div className={'w-100 relative flex flex-row gap-2'}>
                                        {spanData.data && <DescribeSpan node={spanData.data} />}
                                    </div>
                                    <SpanBarWrapper
                                        ref={ref}
                                        // don't set duration container width back onto the element that is generating it
                                        durationContainerWidth={!!ref ? undefined : parentSpanWidth}
                                        maxSpan={timeToSeeSession.data.duration_ms}
                                        spanData={spanData}
                                    />
                                </div>
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
    const { focussedInteraction, processedSpans, currentFacts } = useValues(logic)
    const { showInteractionTrace, showNode } = useActions(logic)

    return (
        <BindLogic logic={traceLogic} props={{ sessionNode: timeToSeeSession }}>
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
                    <ExpandableSpan
                        onClick={showNode}
                        widthTrackingRef={selectedSpanRef}
                        // don't set duration container width back onto the element that is generating it
                        durationContainerWidth={selectedSpanWidth}
                        // the selected span _must_ always have a larger duration than its children
                        maxSpan={focussedInteraction.duration}
                        spanData={focussedInteraction}
                    />
                ) : (
                    <>Choose an interaction in the overview above to see its details</>
                )}

                {focussedInteraction && currentFacts ? <NodeFacts facts={currentFacts} /> : null}
            </div>
        </BindLogic>
    )
}
