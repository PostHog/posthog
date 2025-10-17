interface SessionSummaryErrorCardProps {
    sessionId: string
    errorMessage?: string
}

export function SessionSummaryErrorCard({ sessionId, errorMessage }: SessionSummaryErrorCardProps): JSX.Element {
    return (
        <div className="border border-danger rounded bg-bg-light mb-2">
            <div className="py-3 px-3 flex gap-2">
                <div className="w-3" />
                <div>
                    <div className="flex items-center gap-2 mb-2">
                        <span className="text-base font-bold text-danger">✗</span>
                        <div className="font-mono text-xs text-muted">{sessionId}</div>
                        <span className="text-xs text-muted">•</span>
                        <span className="text-xs text-danger">Failed</span>
                    </div>
                    <div className="text-muted">{errorMessage}</div>
                </div>
            </div>
        </div>
    )
}
