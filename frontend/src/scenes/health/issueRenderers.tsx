import { ComponentType } from 'react'

import { TZLabel } from 'lib/components/TZLabel'

import { GenericIssueRenderer } from './renderers/GenericIssueRenderer'
import { SdkOutdatedRenderer } from './renderers/SdkOutdatedRenderer'
import type { HealthIssue } from './types'

const IngestionWarningRenderer = ({ issue }: { issue: HealthIssue }): JSX.Element => {
    const { warning_type, affected_count, last_seen_at } = issue.payload
    return (
        <div className="text-xs bg-surface-secondary rounded p-2 mt-1 space-y-0.5">
            {warning_type && (
                <div className="flex gap-2">
                    <span className="font-medium">Warning type:</span>
                    <code className="bg-fill-primary px-1 rounded">{warning_type}</code>
                </div>
            )}
            {affected_count != null && (
                <div className="flex gap-2">
                    <span className="font-medium">Affected events:</span>
                    <span>{Number(affected_count).toLocaleString()}</span>
                </div>
            )}
            {last_seen_at && (
                <div className="flex gap-2">
                    <span className="font-medium">Last seen:</span>
                    <TZLabel time={last_seen_at} />
                </div>
            )}
        </div>
    )
}

const PipelineFailureRenderer = ({ issue }: { issue: HealthIssue }): JSX.Element => {
    const { pipeline_name, source_type, error } = issue.payload
    return (
        <div className="text-xs bg-surface-secondary rounded p-2 mt-1 space-y-0.5">
            {pipeline_name && (
                <div className="flex gap-2">
                    <span className="font-medium">Pipeline:</span>
                    <span>{pipeline_name}</span>
                </div>
            )}
            {source_type && source_type !== 'unknown' && (
                <div className="flex gap-2">
                    <span className="font-medium">Source:</span>
                    <span>{source_type}</span>
                </div>
            )}
            {error && (
                <div>
                    <span className="font-medium">Error:</span>
                    <pre className="mt-0.5 whitespace-pre-wrap break-all text-xs bg-fill-primary rounded p-1.5">
                        {error}
                    </pre>
                </div>
            )}
        </div>
    )
}

const HEALTH_ISSUE_RENDERERS: Record<string, ComponentType<{ issue: HealthIssue }>> = {
    sdk_outdated: SdkOutdatedRenderer,
    ingestion_warning: IngestionWarningRenderer,
    external_data_failure: PipelineFailureRenderer,
    materialized_view_failure: PipelineFailureRenderer,
}

export const getIssueRenderer = (kind: string): ComponentType<{ issue: HealthIssue }> => {
    return HEALTH_ISSUE_RENDERERS[kind] ?? GenericIssueRenderer
}
