import { useLayoutEffect, useState } from 'react'

import type { TodayRowTone } from './TodayRow'

/**
 * The line under a row title. A reason goes last and keeps the line to one line, so a long reason is cut with an
 * ellipsis. The row title shows a cut reason in full, because the title's link covers the whole row and takes every
 * hover.
 */
export function TodayRowMeta({
    tone,
    label,
    facts,
    reason,
    onTruncatedChange,
}: {
    tone: TodayRowTone
    label?: string
    facts: string[]
    reason?: string | null
    onTruncatedChange?: (truncated: boolean) => void
}): JSX.Element {
    const [element, setElement] = useState<HTMLParagraphElement | null>(null)

    useLayoutEffect(() => {
        if (!element || !reason || !onTruncatedChange) {
            return
        }
        const checkTruncated = (): void => onTruncatedChange(element.scrollWidth > element.clientWidth + 1)
        checkTruncated()
        const observer = new ResizeObserver(checkTruncated)
        observer.observe(element)
        return () => observer.disconnect()
    }, [element, reason, onTruncatedChange])

    return (
        <p ref={setElement} className="TodayRow__meta" data-single-line={reason ? true : undefined}>
            {[label, ...facts, reason].filter(Boolean).map((part, index) => (
                <span
                    key={`${index}-${part}`}
                    className={index === 0 && label ? 'TodayRow__label' : undefined}
                    data-tone={index === 0 && label ? tone : undefined}
                >
                    {index === 0 ? part : ` · ${part}`}
                </span>
            ))}
        </p>
    )
}
