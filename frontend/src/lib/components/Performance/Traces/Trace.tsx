import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { RefCallback, useState } from 'react'
import clsx from 'clsx'
import {
    SessionData,
    TimeToSeeInteractionNode,
    TimeToSeeNode,
    TimeToSeeSessionNode,
} from '~/queries/nodes/TimeToSeeData/types'
import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyDuration } from 'lib/utils'
import { dayjs } from 'lib/dayjs'
import { IconSad, IconUnfoldLess, IconUnfoldMore } from 'lib/components/icons'
import { getSeriesColor } from 'lib/colors'
import './Trace.scss'
import { LemonButton } from 'lib/components/LemonButton'

export interface SpanProps extends SpanData {
    maxSpan: number
    durationContainerWidth: number | undefined
    widthTrackingRef?: RefCallback<HTMLElement>
    isSelected?: boolean
}

export function Span({
    isSelected,
    start,
    duration,
    data,
    maxSpan,
    durationContainerWidth,
    widthTrackingRef,
    type,
    level = 0,
}: SpanProps): JSX.Element {
    const durationWidth = (duration / maxSpan) * 100
    const startMargin = (start / maxSpan) * 100

    const [isExpanded, setIsExpanded] = useState(false)

    return (
        <div
            className={clsx(
                'w-full border px-4 py-4 flex flex-row justify-between cursor-pointer',
                isSelected && 'bg-muted',
                `Span__${type}`
            )}
        >
            <div className={'w-60 relative flex flex-row'}>
                <LemonButton
                    noPadding
                    status="stealth"
                    onClick={() => setIsExpanded(!isExpanded)}
                    icon={isExpanded ? <IconUnfoldLess /> : <IconUnfoldMore />}
                    title={isExpanded ? 'Collapse span' : 'Expand span'}
                />
                <div className={clsx('h-full relative', level > 0 && 'Span__nested', `w-${(level + 1) * 4}`)} />
                <div className={clsx('flex flex-col')}>
                    <div className={'flex flex-row items-center gap-2'}>
                        {data && 'type' in data ? data?.type : 'session'}{' '}
                        {data && 'data' in data && 'is_frustrating' in data.data && data.data.is_frustrating && (
                            <IconSad />
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
                <div
                    style={{
                        backgroundColor: getSeriesColor(level),
                        width: `${durationWidth}%`,
                        marginLeft: `${startMargin}%`,
                    }}
                    className={'text-white pl-1'}
                >
                    {duration}ms
                </div>
            </div>
        </div>
    )
}

export interface TraceProps {
    timeToSeeSession: TimeToSeeSessionNode
}

interface SpanData {
    type: 'session' | 'interaction' | 'event'
    start: number // milliseconds after session start
    duration: number
    data?: TimeToSeeNode | SessionData
    level?: number
}

interface ProcessSpans {
    spans: SpanData[]
    maxDuration: number
}

function walkSpans(nodes: Array<TimeToSeeNode>, sessionStart: dayjs.Dayjs, level: number = 1): ProcessSpans {
    let spanData: SpanData[] = []
    let maxDuration = 0

    nodes
        .filter((node): node is TimeToSeeInteractionNode => node.type === 'interaction' || node.type === 'event')
        .forEach((node) => {
            // are these all InteractionNodes
            const start = dayjs(node.data.timestamp).diff(sessionStart)
            spanData.push({
                type: node.type,
                start: start,
                duration: node.data.time_to_see_data_ms,
                data: node,
                level,
            })
            maxDuration = start + node.data.time_to_see_data_ms

            const walkedChildren = walkSpans(node.children, sessionStart, level++)
            spanData = spanData.concat(walkedChildren.spans)
            maxDuration = maxDuration > walkedChildren.maxDuration ? maxDuration : walkedChildren.maxDuration
        })
    return { spans: spanData, maxDuration }
}

function flattenSpans(timeToSeeSession: TimeToSeeSessionNode): ProcessSpans {
    const walkedChildren = walkSpans(timeToSeeSession.children, dayjs(timeToSeeSession.data.session_start))
    walkedChildren.spans.unshift({
        type: 'session',
        start: 0,
        duration: timeToSeeSession.data.duration_ms,
        data: timeToSeeSession.data,
    })

    return {
        spans: walkedChildren.spans,
        maxDuration: Math.max(timeToSeeSession.data.duration_ms, walkedChildren.maxDuration),
    }
}

export function Trace({ timeToSeeSession }: TraceProps): JSX.Element {
    const [selectedSpan, setSelectedSpan] = useState<number | null>(null)

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
                    <div
                        key={i}
                        onClick={() => {
                            setSelectedSpan(selectedSpan === i ? null : i)
                        }}
                    >
                        <Span
                            widthTrackingRef={ref}
                            // don't set duration container width back onto the element that is generating it
                            durationContainerWidth={!!ref ? undefined : parentSpanWidth}
                            maxSpan={maxDuration}
                            isSelected={selectedSpan === i}
                            {...spanData}
                        />
                    </div>
                )
            })}
        </div>
    )
}
