import { ReactNode } from 'react'

import { Language } from 'lib/components/CodeSnippet'
import { Link } from 'lib/lemon-ui/Link'
import { Collapsible } from 'lib/ui/Collapsible/Collapsible'

import { ErrorTrackingStackFrame, ErrorTrackingStackFrameContext, ErrorTrackingStackFrameRecord } from '../types'
import { SYMBOL_SETS_DOC_LINK, formatFunctionName, getInstructionAddress } from '../utils'
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
                <FrameContextEmptyState frame={frame} loading={recordLoading} hasRecord={record !== undefined} />
            )}
        </Collapsible.Panel>
    )
}

function FrameContextEmptyState({
    frame,
    loading,
    hasRecord,
}: {
    frame: ErrorTrackingStackFrame
    loading: boolean
    hasRecord: boolean
}): JSX.Element {
    return (
        <div className="bg-fill-expanded px-3 py-2 text-xs text-muted-foreground">
            {getEmptyStateMessage(frame, loading, hasRecord)}
        </div>
    )
}

function getEmptyStateMessage(frame: ErrorTrackingStackFrame, loading: boolean, hasRecord: boolean): ReactNode {
    if (loading) {
        return 'Loading source code...'
    }
    if (!formatFunctionName(frame) && !frame.source) {
        // Symbol sets can only symbolicate a frame we can match by address. Without one, the upload
        // cannot help, so mirror the header and state the SDK gap instead of linking to the docs.
        if (getInstructionAddress(frame)) {
            return (
                <>
                    PostHog could not identify this frame, so there is no source code to show. <UploadSymbolSetsLink />{' '}
                    to symbolicate it.
                </>
            )
        }
        return 'The SDK sent no function name, file name or memory address for this frame, so there is nothing to identify it with.'
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
    // Naming the source map as the cause is only truthful once a record loaded and confirmed the
    // frame has no source. Without a record the batch request may have failed or never ran, so fall
    // back to the neutral statement the frame header uses instead of sending the user to re-upload
    // source maps that were never missing. Source maps also only apply to JavaScript and TypeScript;
    // other runtimes send source code in the event payload.
    if (hasRecord && usesSourceMaps(frame)) {
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
    return 'This frame is resolved, but its source code is not available.'
}

function usesSourceMaps(frame: ErrorTrackingStackFrame): boolean {
    const language = getFrameLanguage(frame)
    return language === Language.JavaScript || language === Language.TypeScript
}

function UploadSymbolSetsLink(): JSX.Element {
    return (
        <Link to={SYMBOL_SETS_DOC_LINK} target="_blank">
            Upload your symbol sets
        </Link>
    )
}
