import { LemonBanner } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'

import { LogsViewer } from '../logs/LogsViewer'
import { renderHogFunctionMessage } from '../logs/renderHogFunctionMessage'

// Transformations run in the ingestion pipeline, not on a cyclotron worker, so they never write to
// `hog_invocation_results`. The standard invocations table would always be empty for them. They do
// write log lines to `log_entries` (source `hog_function`, keyed by function id), so surface those
// here grouped per run, and point at Metrics for success and failure counts.
export function TransformationInvocations({
    id,
    onViewMetrics,
}: {
    id: string
    onViewMetrics: () => void
}): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <LemonBanner type="info">
                Transformations don't store individual runs like destinations do. Each row below is one run and the log
                lines it wrote. For success and failure counts, open the <Link onClick={onViewMetrics}>Metrics</Link>{' '}
                tab.
            </LemonBanner>
            <LogsViewer
                sourceType="hog_function"
                sourceId={id}
                renderMessage={(message) => renderHogFunctionMessage(message)}
            />
        </div>
    )
}
