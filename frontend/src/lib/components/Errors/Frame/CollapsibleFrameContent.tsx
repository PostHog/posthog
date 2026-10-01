import { useValues } from 'kea'

import { Collapsible } from 'lib/ui/Collapsible/Collapsible'

import { errorPropertiesLogic } from '../errorPropertiesLogic'
import { ErrorTrackingStackFrame, ErrorTrackingStackFrameContext, ErrorTrackingStackFrameRecord } from '../types'
import { CodeVariablesInlineBanner } from './CodeVariablesInlineBanner'
import { FrameContext } from './FrameContext'
import { getFrameLanguage } from './frameLanguage'
import { FrameSourceFile } from './FrameSourceFile'
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
    const { code_variables } = frame
    const { getSourceFileTarget } = useValues(errorPropertiesLogic)
    const hasCodeVariables = code_variables && Object.keys(code_variables).length > 0
    const context = record?.context ?? null
    const sourceFileTarget = getSourceFileTarget(frame)
    if (!context && !sourceFileTarget) {
        return null
    }
    const language = getFrameLanguage(frame)
    return (
        <Collapsible.Panel className="border-t-[color:var(--frame-border,var(--color-border-primary))]">
            <div onClick={(e) => context && onFrameContextClick?.(context, e)}>
                {sourceFileTarget ? (
                    <FrameSourceFile target={sourceFileTarget} context={context} language={language} />
                ) : (
                    <FrameContext context={context!} language={language} />
                )}
                {hasCodeVariables ? <FrameVariables variables={code_variables!} /> : <CodeVariablesInlineBanner />}
            </div>
        </Collapsible.Panel>
    )
}
