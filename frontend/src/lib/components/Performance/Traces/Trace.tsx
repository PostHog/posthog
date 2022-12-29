import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { RefCallback } from 'react'

export interface SpanProps {
    duration: number
    start: number
    maxSpan: number
    durationContainerWidth: number | undefined
    widthTrackingRef?: RefCallback<HTMLElement>
}

export function Span({ start, duration, maxSpan, durationContainerWidth, widthTrackingRef }: SpanProps): JSX.Element {
    const durationWidth = (duration / maxSpan) * 100
    const startMargin = (start / maxSpan) * 100
    return (
        <div className={'w-full border px-4 py-2 flex flex-row gap-2 justify-between'}>
            <div className={'whitespace-nowrap'}>Span name</div>
            <div
                ref={widthTrackingRef}
                className={'grow'}
                style={{
                    width: durationContainerWidth || '100%',
                    maxWidth: durationContainerWidth,
                    minWidth: durationContainerWidth,
                }}
            >
                <div
                    style={{
                        backgroundColor: 'green',
                        width: `${durationWidth}%`,
                        marginLeft: `${startMargin}%`,
                    }}
                >
                    {duration}ms
                </div>
            </div>
        </div>
    )
}

export function Trace(): JSX.Element {
    // duration of spans are always ordered descending
    // even if nested
    const spans = [
        [0, 1800],
        [200, 800],
        [950, 230],
        [960, 20],
        [965, 5],
        [970, 5],
        [975, 5],
    ]

    const { ref: parentSpanRef, width: parentSpanWidth } = useResizeObserver()

    return (
        <div className={'flex flex-col gap-2 border rounded p-4'}>
            <h1>The trace title</h1>
            {spans.map(([start, duration], i) => {
                let ref = undefined
                if (duration === 1800) {
                    ref = parentSpanRef
                }
                return (
                    <Span
                        key={i}
                        widthTrackingRef={ref}
                        // don't set duration container width back onto the element that is generating it
                        durationContainerWidth={!!ref ? undefined : parentSpanWidth}
                        start={start}
                        duration={duration}
                        maxSpan={1800}
                    />
                )
            })}
        </div>
    )
}
