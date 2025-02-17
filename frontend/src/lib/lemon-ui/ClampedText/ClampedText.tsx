import React, { useEffect, useState } from 'react'

import { Link } from '../Link'

export interface ClampedTextProps {
    lines: number
    text: string
}

const isCssEllipsisApplied = (elem: HTMLDivElement): boolean => elem.scrollHeight > elem.clientHeight

export const ClampedText = React.forwardRef<HTMLDivElement, ClampedTextProps>(function ClampedText(
    { lines, text },
    ref
) {
    const [localLines, setLocalLines] = useState<number | undefined>(lines)
    const [isExpanded, setIsExpanded] = useState<boolean>(false)
    const [showMore, setShowMore] = useState<boolean>(false)

    const handleToggleShowMore = (show: boolean): void => {
        setShowMore(!showMore)
        setIsExpanded(!isExpanded)
        setLocalLines(show ? undefined : lines)
    }

    const handleConfigElement = (elem: HTMLDivElement): void => {
        if (!elem) {
            return
        }

        if (isCssEllipsisApplied(elem)) {
            if (!showMore || !isExpanded) {
                setShowMore(true)
            }
        } else {
            setShowMore(false)
        }
    }

    useEffect(() => setLocalLines(lines), [lines])

    return (
        <div ref={ref}>
            <TruncatedElement lines={localLines} ref={handleConfigElement} text={text} />
            <div>
                {isExpanded || showMore ? (
                    <Link onClick={() => handleToggleShowMore(!isExpanded)}>
                        {isExpanded ? 'Show less' : 'Show more'}
                    </Link>
                ) : null}
            </div>
        </div>
    )
})

const TruncatedElement = React.forwardRef<HTMLDivElement, { lines?: number; text: string }>(function TruncatedElement(
    { text, lines },
    ref
) {
    return (
        <span
            // eslint-disable-next-line react/forbid-dom-props
            style={
                lines
                    ? {
                          overflow: 'hidden',
                          display: '-webkit-box',
                          WebkitBoxOrient: 'vertical',
                          WebkitLineClamp: lines,
                      }
                    : {}
            }
            ref={ref}
        >
            {text}
        </span>
    )
})
