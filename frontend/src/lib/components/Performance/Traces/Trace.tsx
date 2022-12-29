import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { RefCallback, useState } from 'react'
import clsx from 'clsx'

export interface SpanProps {
    duration: number
    start: number
    maxSpan: number
    durationContainerWidth: number | undefined
    widthTrackingRef?: RefCallback<HTMLElement>
    isSelected?: boolean
}

export function Span({
    isSelected,
    start,
    duration,
    maxSpan,
    durationContainerWidth,
    widthTrackingRef,
}: SpanProps): JSX.Element {
    const durationWidth = (duration / maxSpan) * 100
    const startMargin = (start / maxSpan) * 100
    return (
        <div
            className={clsx(
                'w-full border px-4 py-2 flex flex-row gap-2 justify-between cursor-pointer',
                isSelected && 'bg-muted'
            )}
        >
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
    const [selectedSpan, setSelectedSpan] = useState<number | null>(null)
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
                            start={start}
                            duration={duration}
                            maxSpan={1800}
                            isSelected={selectedSpan === i}
                        />
                    </div>
                )
            })}
        </div>
    )
}
