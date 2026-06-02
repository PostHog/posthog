import { getLanguage } from 'lib/components/CodeSnippet/CodeSnippet'
import { Collapsible } from 'lib/ui/Collapsible/Collapsible'

import { ErrorTrackingStackFrame, ErrorTrackingStackFrameContext, ErrorTrackingStackFrameRecord } from '../types'
import { CodeVariablesInlineBanner } from './CodeVariablesInlineBanner'
import { FrameContext } from './FrameContext'
import { FrameVariables } from './FrameVariables'
import { SymbolSetLink } from './SymbolSetLink'

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
        <Collapsible.Panel>
            <div onClick={(e) => onFrameContextClick?.(record.context!, e)}>
                <FrameContext context={record.context} language={getLanguage(lang)} />
                {hasCodeVariables ? <FrameVariables variables={code_variables!} /> : <CodeVariablesInlineBanner />}
            </div>
            {record.symbol_set_ref && (
                <div className="flex items-center gap-2 px-2 py-1 border-t text-xs text-secondary overflow-hidden">
                    <span className="shrink-0">Symbol set</span>
                    <SymbolSetLink symbolSetRef={record.symbol_set_ref} resolved className="min-w-0" />
                </div>
            )}
        </Collapsible.Panel>
    )
}
