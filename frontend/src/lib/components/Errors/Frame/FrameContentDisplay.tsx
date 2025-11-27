import { getLanguage } from 'lib/components/CodeSnippet/CodeSnippet'

import { ErrorTrackingStackFrame, ErrorTrackingStackFrameContext, ErrorTrackingStackFrameRecord } from '../types'
import { CodeVariablesInlineBanner } from './CodeVariablesInlineBanner'
import { FrameContext } from './FrameContext'
import { FrameVariables } from './FrameVariables'

export interface FrameContentDisplayProps {
    frame: ErrorTrackingStackFrame
    record: ErrorTrackingStackFrameRecord

    onFrameContextClick?: (context: ErrorTrackingStackFrameContext, event: React.MouseEvent<HTMLDivElement>) => void
}

export function FrameContentDisplay({ frame, record, onFrameContextClick }: FrameContentDisplayProps): JSX.Element {
    const { lang, code_variables } = frame
    const hasCodeVariables = code_variables && Object.keys(code_variables).length > 0
    return record && record.context ? (
        <div onClick={(e) => onFrameContextClick?.(record.context!, e)}>
            <FrameContext context={record.context} language={getLanguage(lang)} />
            {hasCodeVariables ? <FrameVariables variables={code_variables!} /> : <CodeVariablesInlineBanner />}
        </div>
    ) : null
}
