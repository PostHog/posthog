import { IconCheck, IconEllipsis, IconRefresh, IconRevert, IconServer, IconX } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonMenu, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { severityToTagType } from '../../healthUtils'
import type { HealthIssue } from '../../types'
import { getErrorLabelForMaterializedView } from '../../utils/materializedViewErrors'
import type { CategoryDetailContentProps } from '../categoryDetailTypes'

export default function DataModelingDetailContent({
    issues,
    statusSummary,
    isLoading,
    onDismiss,
    onUndismiss,
    onRefresh,
    showDismissed,
    onSetShowDismissed,
}: CategoryDetailContentProps): JSX.Element {
    return (
        <div className="flex flex-col gap-4 max-w-3xl">
            <LemonBanner type={statusSummary.isHealthy ? 'success' : 'warning'}>
                <div className="flex items-center justify-between w-full">
                    <div>
                        <div className="font-semibold">
                            {statusSummary.isHealthy
                                ? 'All materialized views are running correctly'
                                : `${statusSummary.count} materialized view${statusSummary.count === 1 ? '' : 's'} ha${statusSummary.count === 1 ? 's' : 've'} failed`}
                        </div>
                        {!statusSummary.isHealthy && (
                            <div className="text-sm mt-0.5">Query performance and data freshness may be affected.</div>
                        )}
                    </div>
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconRefresh />}
                        onClick={onRefresh}
                        loading={isLoading}
                    >
                        Refresh
                    </LemonButton>
                </div>
            </LemonBanner>

            <p className="text-sm text-secondary mb-0">
                Materialized views pre-compute query results to improve dashboard performance. When they fail, queries
                fall back to computing results on the fly, which may be slower.
            </p>

            {!statusSummary.isHealthy && (
                <>
                    <div className="flex items-center justify-end gap-1">
                        <LemonMenu
                            items={[
                                {
                                    label: 'Show dismissed',
                                    icon: showDismissed ? <IconCheck /> : undefined,
                                    onClick: () => onSetShowDismissed(!showDismissed),
                                },
                            ]}
                            placement="bottom-end"
                        >
                            <LemonButton icon={<IconEllipsis />} type="tertiary" size="small" />
                        </LemonMenu>
                    </div>

                    <div className="flex flex-col gap-3">
                        {issues.map((issue) => (
                            <MaterializedViewCard
                                key={issue.id}
                                issue={issue}
                                onDismiss={onDismiss}
                                onUndismiss={onUndismiss}
                            />
                        ))}
                    </div>
                </>
            )}

            <div className="flex items-center gap-3 text-xs text-muted">
                <Link to="https://posthog.com/docs/data-warehouse">Documentation</Link>
                <span>&middot;</span>
                <Link to="https://posthog.com/support">Contact support</Link>
            </div>
        </div>
    )
}

function MaterializedViewCard({
    issue,
    onDismiss,
    onUndismiss,
}: {
    issue: HealthIssue
    onDismiss: (id: string) => void
    onUndismiss: (id: string) => void
}): JSX.Element {
    const { pipeline_name, error } = issue.payload
    const errorHelp = getErrorLabelForMaterializedView(error ?? null)

    return (
        <div className="border rounded p-4 bg-surface-primary">
            <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0">
                    <IconServer className="size-4 text-muted shrink-0" />
                    <span className="font-medium truncate">{pipeline_name ?? 'Unknown view'}</span>
                    <LemonTag type={severityToTagType(issue.severity)} size="small" className="shrink-0">
                        {issue.severity}
                    </LemonTag>
                </div>
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    icon={issue.dismissed ? <IconRevert /> : <IconX />}
                    tooltip={issue.dismissed ? 'Undismiss' : 'Dismiss'}
                    onClick={() => (issue.dismissed ? onUndismiss(issue.id) : onDismiss(issue.id))}
                />
            </div>
            {error && (
                <pre className="mt-2 whitespace-pre-wrap break-all text-xs bg-surface-secondary rounded p-2">
                    {error}
                </pre>
            )}
            {errorHelp && <div className="text-xs text-muted mt-2 ml-6">{errorHelp}</div>}
            <div className="text-xs text-muted mt-2 ml-6">
                <TZLabel time={issue.created_at} />
            </div>
        </div>
    )
}
