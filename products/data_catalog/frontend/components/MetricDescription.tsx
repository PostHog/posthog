import { useEffect, useRef, useState } from 'react'

import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

/** A metric description clamped to two lines, with the full text in a tooltip when it overflows. */
export function MetricDescription({ description }: { description: string }): JSX.Element {
    const contentRef = useRef<HTMLDivElement | null>(null)
    const [isOverflowing, setIsOverflowing] = useState(false)
    // The column resizes with the scene (e.g. opening a side panel), which changes the line count.
    const { width } = useResizeObserver({ ref: contentRef })

    useEffect(() => {
        if (contentRef.current) {
            setIsOverflowing(contentRef.current.scrollHeight > contentRef.current.clientHeight)
        }
    }, [description, width])

    // Images stay disabled so a stored image URL can't beacon other viewers.
    const markdown = (
        <LemonMarkdown lowKeyHeadings disableImages>
            {description}
        </LemonMarkdown>
    )

    return (
        <Tooltip title={isOverflowing ? <div className="max-w-120">{markdown}</div> : undefined}>
            <div ref={contentRef} className="max-w-[30rem] line-clamp-2">
                {markdown}
            </div>
        </Tooltip>
    )
}
