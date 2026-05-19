import React from 'react'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { cn } from 'lib/utils/css-classes'

export interface SeekbarSegmentRange {
    index: number
    name: string
    startMs: number
    endMs: number
    success: boolean | null
}

export const SeekbarSegments = React.memo(function SeekbarSegments({
    segments,
    endTimeMs,
    onSeekToSegment,
}: {
    segments: SeekbarSegmentRange[] | null
    endTimeMs: number
    onSeekToSegment: (startMs: number) => void
}): JSX.Element | null {
    if (!segments || segments.length === 0 || endTimeMs <= 0) {
        return null
    }

    return (
        <div className="PlayerSeekbar__segments">
            {segments.map((segment) => {
                const left = Math.max(0, Math.min(100, (segment.startMs / endTimeMs) * 100))
                const width = Math.max(0.5, Math.min(100 - left, ((segment.endMs - segment.startMs) / endTimeMs) * 100))

                return (
                    <Tooltip key={segment.index} title={segment.name} placement="top">
                        <div
                            className={cn('PlayerSeekbar__segment', {
                                'PlayerSeekbar__segment--success': segment.success === true,
                                'PlayerSeekbar__segment--failure': segment.success === false,
                                'PlayerSeekbar__segment--unknown': segment.success === null,
                            })}
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{
                                left: `${left}%`,
                                width: `${width}%`,
                            }}
                            onClick={(e) => {
                                e.stopPropagation()
                                onSeekToSegment(segment.startMs)
                            }}
                        />
                    </Tooltip>
                )
            })}
        </div>
    )
})
