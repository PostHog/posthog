import { combineUrl } from 'kea-router'

import { Link } from '@posthog/lemon-ui'

import { Collapsible } from 'lib/ui/Collapsible/Collapsible'
import { urls } from 'scenes/urls'

import { ErrorTrackingStackFrame } from '../types'
import { formatFunctionName, getInstructionAddress } from '../utils'

export const SYMBOL_SETS_DOC_LINK = 'https://posthog.com/docs/error-tracking/upload-source-maps'

export type FrameUnavailableReason = 'no_identifier' | 'address_only' | 'unresolved' | 'no_source'

export function getFrameUnavailableReason(frame: ErrorTrackingStackFrame): FrameUnavailableReason {
    if (!formatFunctionName(frame) && !frame.source) {
        return getInstructionAddress(frame) ? 'address_only' : 'no_identifier'
    }
    return frame.resolved ? 'no_source' : 'unresolved'
}

const REASON_COPY: Record<FrameUnavailableReason, string[]> = {
    unresolved: [
        'PostHog could not resolve this frame, so there is no source code to show.',
        'Upload the symbol set for this release to see the original source code.',
    ],
    no_source: [
        'PostHog resolved this frame, but its symbol set has no source code.',
        'Include the source code when you upload the symbol set to see it here.',
    ],
    address_only: [
        'The SDK sent only a memory address for this frame.',
        'Upload the symbol set for this build to resolve the address to a function and file.',
    ],
    no_identifier: [
        'The SDK sent no function name, file name or memory address for this frame, so there is nothing to show.',
    ],
}

export function FrameUnavailablePanel({ frame }: { frame: ErrorTrackingStackFrame }): JSX.Element {
    const reason = getFrameUnavailableReason(frame)

    return (
        <Collapsible.Panel className="border-t-[color:var(--frame-border,var(--color-border-primary))]">
            <div className="flex flex-col gap-1 px-2 py-2 text-xs" data-attr="frame-unavailable-reason">
                {REASON_COPY[reason].map((line) => (
                    <p key={line} className="m-0">
                        {line}
                    </p>
                ))}
                {frame.resolve_failure && <p className="m-0 text-muted-foreground">{frame.resolve_failure}</p>}
                {reason !== 'no_identifier' && (
                    <div className="flex gap-3">
                        <Link
                            to={
                                combineUrl(
                                    urls.errorTracking(),
                                    { activeTab: 'configuration' },
                                    { selectedSetting: 'error-tracking-symbol-sets' }
                                ).url
                            }
                            data-attr="frame-unavailable-symbol-sets"
                        >
                            Manage symbol sets
                        </Link>
                        <Link to={SYMBOL_SETS_DOC_LINK} target="_blank" data-attr="frame-unavailable-docs">
                            Read the docs
                        </Link>
                    </div>
                )}
            </div>
        </Collapsible.Panel>
    )
}
