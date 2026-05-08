import * as React from 'react'

import { cn } from './lib/utils'
import { Skeleton } from './skeleton'

type SkeletonTextProps = {
    lines?: number
    className?: string
    minWidth?: number // %
    maxWidth?: number // %
}

function SkeletonText({ lines = 3, className, minWidth = 60, maxWidth = 100 }: SkeletonTextProps): React.ReactElement {
    // stable random widths per render (no layout shift on re-render)
    const widths = React.useMemo(() => {
        return Array.from({ length: lines }).map((_, i) => {
            if (i === 0) {
                return `${maxWidth}%`
            }
            if (i === lines - 1) {
                // last line shorter
                return `${Math.max(minWidth, 40)}%`
            }
            const rand = Math.random() * (maxWidth - minWidth) + minWidth
            return `${Math.round(rand)}%`
        })
    }, [lines, minWidth, maxWidth])

    return (
        <div data-quill className={cn('flex flex-col', className)}>
            {widths.map((w, i) => (
                <span
                    key={i}
                    className="relative block w-full"
                    style={{
                        height: '1lh', // 🔑 matches actual line-height
                    }}
                >
                    <Skeleton
                        className="absolute left-0 right-auto"
                        style={{
                            width: w,
                            height: '0.7em', // “ink” height
                            top: '50%',
                            transform: 'translateY(-50%)',
                        }}
                    />
                </span>
            ))}
        </div>
    )
}

export { SkeletonText }
