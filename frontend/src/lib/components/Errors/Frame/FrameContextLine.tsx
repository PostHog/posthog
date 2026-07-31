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
    return (
        <div
            className={clsx(
                'border-l-2',
                highlight
                    ? 'border-l-danger bg-[color-mix(in_oklab,var(--color-bg-fill-error-highlight)_50%,transparent)]'
                    : 'border-l-transparent bg-surface-primary'
            )}
        >
            {sortedLines.map(({ number, line }) => (
                <div key={number} className="flex">
                    <div className="w-12 shrink-0 pr-3 text-right text-secondary tabular-nums select-none">
                        {number}
                    </div>
                    <CodeLine text={line} wrapLines={true} language={language} />
                </div>
            ))}
        </div>
    )
}
