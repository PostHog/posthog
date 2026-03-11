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
        <div className="overflow-x-auto [&_span]:!whitespace-pre">
            <div className="w-fit min-w-full">
                <FrameContextLine lines={before} language={language} />
                <FrameContextLine lines={[line]} language={language} highlight />
                <FrameContextLine lines={after} language={language} />
            </div>
        </div>
    )
}
