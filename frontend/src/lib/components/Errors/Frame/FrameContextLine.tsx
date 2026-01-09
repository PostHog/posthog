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
        <div className={highlight ? 'bg-fill-error-highlight' : 'bg-surface-primary'}>
            {sortedLines.map(({ number, line }) => (
                <div key={number} className="flex">
                    <div className="w-12 text-center">{number}</div>
                    <CodeLine text={line} wrapLines={true} language={language} />
                </div>
            ))}
        </div>
    )
}
