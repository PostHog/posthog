import { LemonBanner, LemonSkeleton, Spinner } from '@posthog/lemon-ui'

import type { SummaryItemKind, SummaryModeState, SummaryRequestError } from '../types'
import { SummarizeButton } from './SummarizeButton'
import { SummaryContent } from './SummaryContent'

export interface SummaryModeViewProps {
    state: SummaryModeState
    requesting: boolean
    requestError: SummaryRequestError | null
    consentGiven: boolean
    onRequest: () => void
    onRegenerate: () => void
    onReload: () => void
    onSelectStep: (nodeId: string, kind: SummaryItemKind) => void
}

const REQUEST_ERROR_MESSAGES: Record<SummaryRequestError, string> = {
    throttled: "You've reached the limit for summaries. Try again later.",
    failed: "We couldn't start the summary. Try again.",
}

export function SummaryModeView({
    state,
    requesting,
    requestError,
    consentGiven,
    onRequest,
    onRegenerate,
    onReload,
    onSelectStep,
}: SummaryModeViewProps): JSX.Element {
    const requestErrorBanner = requestError ? (
        <LemonBanner type="error" className="w-full">
            {REQUEST_ERROR_MESSAGES[requestError]}
        </LemonBanner>
    ) : null
    switch (state.status) {
        case 'loading':
            return <LemonSkeleton repeat={4} className="h-5" />
        case 'error':
            return (
                <LemonBanner
                    type="error"
                    action={{ children: 'Retry', onClick: onReload, 'data-attr': 'trace-view-summary-reload' }}
                >
                    We couldn't load the summary.
                </LemonBanner>
            )
        case 'none':
            return (
                <div className="flex flex-col items-start gap-3">
                    <p className="m-0 text-secondary">
                        Get a short summary of this trace, with links to the steps it mentions.
                    </p>
                    {requestErrorBanner}
                    <SummarizeButton
                        label="Summarize"
                        type="primary"
                        onClick={onRequest}
                        loading={requesting}
                        consentGiven={consentGiven}
                        dataAttr="trace-view-summarize"
                    />
                </div>
            )
        case 'pending':
            return (
                <div className="flex items-center gap-2 text-secondary">
                    <Spinner />
                    <span>Summarizing this trace. This can take a minute.</span>
                </div>
            )
        case 'failed':
            return (
                <div className="flex flex-col items-start gap-3">
                    <LemonBanner type="error" className="w-full">
                        {state.message}
                    </LemonBanner>
                    {requestErrorBanner}
                    {state.retryable && (
                        <SummarizeButton
                            label="Retry"
                            type="secondary"
                            onClick={onRequest}
                            loading={requesting}
                            consentGiven={consentGiven}
                            dataAttr="trace-view-summary-retry"
                        />
                    )}
                </div>
            )
        case 'ready':
            return (
                <div className="flex flex-col gap-3">
                    {requestErrorBanner}
                    <SummaryContent
                        summary={state.summary}
                        onSelectStep={onSelectStep}
                        actions={
                            <SummarizeButton
                                label="Regenerate"
                                type="secondary"
                                onClick={onRegenerate}
                                loading={requesting}
                                consentGiven={consentGiven}
                                dataAttr="trace-view-summary-regenerate"
                            />
                        }
                    />
                </div>
            )
    }
}
