import { Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { BindLogic, useValues } from 'kea'
import { getSeriesColor } from 'lib/colors'
import { TZLabel } from 'lib/components/TZLabel'
import { IconSad } from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { humanFriendlyDuration, humanFriendlyMilliseconds } from 'lib/utils'
import { RefCallback, useEffect, useState } from 'react'
import useResizeObserver from 'use-resize-observer'

import { isInteractionNode, isQueryNode, isSessionNode, TimeToSeeNode, TimeToSeeSessionNode } from '../types'
import { sessionNodeFacts, SpanData, traceLogic } from './traceLogic'

export interface TraceProps {
    timeToSeeSession: TimeToSeeSessionNode
}

export interface SpanProps {
    maxSpan: number
    durationContainerWidth: number | undefined
    spanData: SpanData
    widthTrackingRef?: RefCallback<HTMLElement>
    onClick: (s: SpanData) => void
    parentStart?: number
}

function SpanBar({
    spanData,
    maxSpan,
    parentStart,
}: Pick<SpanProps, 'spanData' | 'maxSpan' | 'parentStart'>): JSX.Element {
    const [durationWidth, setDurationWidth] = useState<number>(0)
    const [startMargin, setStartMargin] = useState<number>(0)

    useEffect(() => {
        const nextDurationWidth = (spanData.duration / maxSpan) * 100
        const nextStartMargin = ((spanData.start - (parentStart || 0)) / maxSpan) * 100
        if (nextDurationWidth != durationWidth) {
            setDurationWidth(nextDurationWidth)
        }
        if (nextStartMargin !== startMargin) {
            setStartMargin(nextStartMargin)
        }
    }, [spanData, maxSpan])

    return (
        <div className={clsx('h-full flex relative flex-row')}>
            <div
                /* eslint-disable-next-line react/forbid-dom-props */
                style={{
                    backgroundColor: getSeriesColor(spanData.depth),
                    width: `${durationWidth}%`,
                    marginLeft: `${startMargin}%`,
                }}
                className="text-white pl-1"
            >
                <span>{humanFriendlyMilliseconds(spanData.duration)}</span>
            </div>
        </div>
    )
}

function DescribeSpan({ node }: { node: TimeToSeeNode }): JSX.Element {
    const isFrustratingSession = isSessionNode(node) && node.data.frustrating_interactions_count > 0
    const hasIsFrustrating = isInteractionNode(node) || isQueryNode(node)
    const isFrustratingInteraction = hasIsFrustrating && !!node.data.is_frustrating
    return (
        <div className={clsx('flex flex-row items-center gap-2')}>
            {isSessionNode(node) ? 'session' : null}

            {(isFrustratingSession || isFrustratingInteraction) && (
                <Tooltip title="This was frustrating because it took longer than 5 seconds">
                    <IconSad />
                </Tooltip>
            )}
            {isInteractionNode(node) && (
                <>
                    <div>
                        {node.data.type}
                        {node.data.action && <> - {node.data.action}</>}
                    </div>
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
    parentStart?: number
}): JSX.Element {
    return (
        <div
            ref={props.ref}
            className="grow self-center"
            /* eslint-disable-next-line react/forbid-dom-props */
            style={{
                width: props.durationContainerWidth || '100%',
            }}
        >
            <SpanBar maxSpan={props.maxSpan} spanData={props.spanData} parentStart={props.parentStart} />
        </div>
    )
}

function NodeFacts({ facts }: { facts: Record<string, any> }): JSX.Element {
    return (
        <div className={clsx('w-full border px-2 py-1 flex flex-col justify-between')}>
            {Object.entries(facts)
                .filter((entry) => entry[1] !== undefined && entry[1] !== '')
                .map(([key, fact], index) => {
                    return (
                        <div key={index} className="flex flex-row w-full overflow-auto whitespace-nowrap">
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
    parentSpanWidth,
    parentSpanRef,
}: {
    processedSpans: SpanData[]
    timeToSeeSession: TimeToSeeSessionNode
    parentSpanRef: RefCallback<HTMLElement>
    parentSpanWidth: number | undefined
}): JSX.Element {
    const { maxTimePoint } = useValues(traceLogic)
    return (
        <>
            <div className="flex flex-col gap-2 border rounded p-4">
                <NodeFacts facts={sessionNodeFacts(timeToSeeSession)} />
                <h1 className="mb-0">Session Interactions</h1>
                <LemonBanner type="info">
                    During sessions we capture metrics as "Interactions". Interactions can contain events and queries.
                    Any interaction, event, or query that takes longer than 5 seconds is classified as frustrating.
                    {/* Click on an interaction below to see more details. */}
                </LemonBanner>
                <div>
                    {processedSpans
                        .filter((spanData) => ['interaction', 'session'].includes(spanData.type))
                        .map((spanData, i) => {
                            let ref = undefined
                            if (spanData.type === 'session') {
                                ref = parentSpanRef
                            }

                            return (
                                <div key={i}>
                                    <div
                                        className={clsx(
                                            'w-full border px-2 py-1 flex flex-row justify-between',
                                            `Span__${spanData.type}`
                                        )}
                                    >
                                        <div className="w-100 relative flex flex-row gap-2">
                                            {spanData.data && <DescribeSpan node={spanData.data} />}
                                        </div>
                                        <SpanBarWrapper
                                            ref={ref}
                                            // don't set duration container width back onto the element that is generating it
                                            durationContainerWidth={ref ? undefined : parentSpanWidth}
                                            maxSpan={maxTimePoint}
                                            spanData={spanData}
                                        />
                                    </div>
                                </div>
                            )
                        })}
                </div>
            </div>
        </>
    )
}

export function Trace({ timeToSeeSession }: TraceProps): JSX.Element {
    const { ref: parentSpanRef, width: parentSpanWidth } = useResizeObserver()

    const logic = traceLogic({ sessionNode: timeToSeeSession })
    const { processedSpans } = useValues(logic)

    return (
        <BindLogic logic={traceLogic} props={{ sessionNode: timeToSeeSession }}>
            <div className="flex flex-col gap-1 border rounded p-4">
                <h2>{timeToSeeSession.data.session_id}</h2>
                <div>
                    session length: {humanFriendlyDuration(timeToSeeSession.data.total_interaction_time_to_see_data_ms)}
                </div>
                <div>
                    session start: <TZLabel time={timeToSeeSession.data.session_start} />
                </div>
                <TraceOverview
                    parentSpanRef={parentSpanRef}
                    parentSpanWidth={parentSpanWidth}
                    processedSpans={processedSpans}
                    timeToSeeSession={timeToSeeSession}
                />
            </div>
        </BindLogic>
    )
}
