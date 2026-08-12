import { Language } from 'lib/components/CodeSnippet'

import { ErrorTrackingStackFrameContext } from '../types'
import { FrameContextLine } from './FrameContextLine'

export function FrameContext({
    context,
    language,
}: {
    context: ErrorTrackingStackFrameContext
    language: Language
}): JSX.Element {
    const { before, line, after } = context
    return (
        // Deliberately quill's --card rather than the app surface the frame chrome uses:
        // in dark mode the source lines then read as a near-black editor block.
        <div className="overflow-x-auto overscroll-x-none bg-[var(--card)] [&_span]:!whitespace-pre">
            <div className="w-fit min-w-full">
                <FrameContextLine lines={before} language={language} />
                <FrameContextLine lines={[line]} language={language} highlight />
                <FrameContextLine lines={after} language={language} />
            </div>
        </div>
    )
}
