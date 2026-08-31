import { ReactNode } from 'react'

import { Link } from 'lib/lemon-ui/Link'
import { Collapsible } from 'lib/ui/Collapsible/Collapsible'

import { ErrorTrackingStackFrame, ErrorTrackingStackFrameContext, ErrorTrackingStackFrameRecord } from '../types'
import { SYMBOL_SETS_DOC_LINK, formatFunctionName } from '../utils'
import { CodeVariablesInlineBanner } from './CodeVariablesInlineBanner'
import { FrameContext } from './FrameContext'
import { getFrameLanguage } from './frameLanguage'
import { FrameVariables } from './FrameVariables'

export interface CollapsibleFrameContentProps {
    frame: ErrorTrackingStackFrame
    record?: ErrorTrackingStackFrameRecord
    recordLoading: boolean

    onFrameContextClick?: (context: ErrorTrackingStackFrameContext, event: React.MouseEvent<HTMLDivElement>) => void
}

export function CollapsibleFrameContent({
    frame,
    record,
    recordLoading,
    onFrameContextClick,
}: CollapsibleFrameContentProps): JSX.Element {
    const { code_variables } = frame
    const hasCodeVariables = code_variables && Object.keys(code_variables).length > 0
    const context = record?.context

    return (
        <Collapsible.Panel className="border-t-[color:var(--frame-border,var(--color-border-primary))]">
            {context ? (
                <div onClick={(e) => onFrameContextClick?.(context, e)}>
                    <FrameContext context={context} language={getFrameLanguage(frame)} />
                    {hasCodeVariables ? <FrameVariables variables={code_variables!} /> : <CodeVariablesInlineBanner />}
                </div>
            ) : (
                <FrameContextEmptyState frame={frame} loading={recordLoading} />
            )}
        </Collapsible.Panel>
    )
}

function FrameContextEmptyState({ frame, loading }: { frame: ErrorTrackingStackFrame; loading: boolean }): JSX.Element {
    return (
        <div className="bg-fill-expanded px-3 py-2 text-xs text-muted-foreground">
            {getEmptyStateMessage(frame, loading)}
        </div>
    )
}

function getEmptyStateMessage(frame: ErrorTrackingStackFrame, loading: boolean): ReactNode {
    if (loading) {
        return 'Loading source code...'
    }
    if (!formatFunctionName(frame) && !frame.source) {
        return (
            <>
                PostHog could not identify this frame, so there is no source code to show. <UploadSymbolSetsLink /> to
                symbolicate it.
            </>
        )
    }
    if (!frame.in_app) {
        return 'This is a vendor frame, so its source code is not available.'
    }
    if (!frame.resolved) {
        return (
            <>
                This frame is not resolved yet. <UploadSymbolSetsLink /> to see its source code.
            </>
        )
    }
    return (
        <>
            This frame is resolved, but its source code is not available. This usually means the source map was not
            uploaded.{' '}
            <Link to={SYMBOL_SETS_DOC_LINK} target="_blank">
                Learn how to upload source maps
            </Link>
            .
        </>
    )
}

function UploadSymbolSetsLink(): JSX.Element {
    return (
        <Link to={SYMBOL_SETS_DOC_LINK} target="_blank">
            Upload your symbol sets
        </Link>
    )
}
