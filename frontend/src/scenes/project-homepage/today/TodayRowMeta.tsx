import { useLayoutEffect, useState } from 'react'

import type { TodayRowTone } from './TodayRow'

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
