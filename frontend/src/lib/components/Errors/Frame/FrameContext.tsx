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
        <>
            <FrameContextLine lines={before} language={language} />
            <FrameContextLine lines={[line]} language={language} highlight />
            <FrameContextLine lines={after} language={language} />
        </>
    )
}
