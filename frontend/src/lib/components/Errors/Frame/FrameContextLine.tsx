import clsx from 'clsx'
import { useMemo } from 'react'

import { Language } from 'lib/components/CodeSnippet'
import { CodeLine } from 'lib/components/CodeSnippet/CodeSnippet'

import { ErrorTrackingStackFrameContextLine } from '../types'

export function FrameContextLine({
    lines,
    language,
    highlight,
}: {
    lines: ErrorTrackingStackFrameContextLine[]
    language: Language
    highlight?: boolean
}): JSX.Element {
    const sortedLines = useMemo(() => [...lines].sort((a, b) => a.number - b.number), [lines])
    const backgroundClassName = highlight
        ? 'bg-[var(--card)] shadow-[inset_0_0_0_9999px_color-mix(in_oklab,var(--destructive)_50%,transparent)]'
        : 'bg-[var(--card)]'

    return (
        <div className={backgroundClassName}>
            {sortedLines.map(({ number, line }) => (
                <div key={number} className="flex">
                    <div
                        className={clsx(
                            'sticky left-0 z-10 w-16 shrink-0 border-l-2 pr-5 text-right text-muted-foreground tabular-nums select-none',
                            highlight ? 'border-l-[var(--destructive-foreground)]' : 'border-l-[var(--card)]',
                            backgroundClassName
                        )}
                    >
                        {number}
                    </div>
                    <CodeLine text={line} wrapLines={false} language={language} />
                </div>
            ))}
        </div>
    )
}
