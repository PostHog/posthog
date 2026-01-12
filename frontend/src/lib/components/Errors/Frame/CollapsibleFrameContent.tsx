import { getLanguage } from 'lib/components/CodeSnippet/CodeSnippet'
import { CollapsiblePrimitiveContent } from 'lib/ui/CollapsiblePrimitive/CollapsiblePrimitive'

import { ErrorTrackingStackFrame, ErrorTrackingStackFrameContext, ErrorTrackingStackFrameRecord } from '../types'
import { CodeVariablesInlineBanner } from './CodeVariablesInlineBanner'
import { FrameContext } from './FrameContext'
import { FrameVariables } from './FrameVariables'

export interface CollapsibleFrameContentProps {
    frame: ErrorTrackingStackFrame
    record?: ErrorTrackingStackFrameRecord

    onFrameContextClick?: (context: ErrorTrackingStackFrameContext, event: React.MouseEvent<HTMLDivElement>) => void
}

export function CollapsibleFrameContent({
    frame,
    record,
    onFrameContextClick,
}: CollapsibleFrameContentProps): JSX.Element | null {
    const { lang, code_variables } = frame
    const hasCodeVariables = code_variables && Object.keys(code_variables).length > 0
    if (!record || !record.context) {
        return null
    }
    return (
        <CollapsiblePrimitiveContent className="transition-[height] border-t-1">
            <div onClick={(e) => onFrameContextClick?.(record.context!, e)}>
                <FrameContext context={record.context} language={getLanguage(lang)} />
                {hasCodeVariables ? <FrameVariables variables={code_variables!} /> : <CodeVariablesInlineBanner />}
            </div>
        </CollapsiblePrimitiveContent>
    )
}
