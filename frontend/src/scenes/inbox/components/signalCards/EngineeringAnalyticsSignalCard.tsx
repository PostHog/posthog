import { IconClock, IconGithub, IconWarning } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { percentage } from 'lib/utils/numbers'
import type { SignalNode } from 'scenes/debug/signals/types'

import type {
    EngineeringAnalyticsCIBrokenMasterSignalExtraApi,
    EngineeringAnalyticsCIDurationRegressionSignalExtraApi,
    EngineeringAnalyticsCIFlakyCheckSignalExtraApi,
} from 'products/signals/frontend/generated/api.schemas'

import { SignalCardShell } from './SignalCardShell'
import type { SignalCardEntry, SignalCardProps } from './types'

type RepoWorkflowExtra = Record<string, unknown> & { repo_owner: string; repo_name: string; workflow_name: string }

/** Every engineering_analytics CI signal carries repo + workflow identity; the rest is per-type. */
function hasRepoWorkflow(value: unknown): value is RepoWorkflowExtra {
    if (typeof value !== 'object' || value === null) {
        return false
    }
    const extra = value as Record<string, unknown>
    return (
        typeof extra.repo_owner === 'string' &&
        typeof extra.repo_name === 'string' &&
        typeof extra.workflow_name === 'string'
    )
}

/** The headline metric tag, switched on the CI signal variant. */
function MetricTag({ signal }: { signal: SignalNode }): JSX.Element | null {
    const extra = signal.extra
    switch (signal.source_type) {
        case 'ci_flaky_check': {
            const e = extra as Record<string, unknown> & EngineeringAnalyticsCIFlakyCheckSignalExtraApi
            return (
                <LemonTag type="warning" size="small" icon={<IconWarning />}>
                    Flaky · {e.flaky_count}/{e.total_commits} commits
                </LemonTag>
            )
        }
        case 'ci_broken_master': {
            const e = extra as Record<string, unknown> & EngineeringAnalyticsCIBrokenMasterSignalExtraApi
            return (
                <LemonTag type="danger" size="small" icon={<IconWarning />}>
                    {e.branch} · {percentage(e.success_rate, 0)} pass
                </LemonTag>
            )
        }
        case 'ci_duration_regression': {
            const e = extra as Record<string, unknown> & EngineeringAnalyticsCIDurationRegressionSignalExtraApi
            return (
                <LemonTag type="warning" size="small" icon={<IconClock />}>
                    p95 +{percentage(e.pct_increase, 0)}
                </LemonTag>
            )
        }
        default:
            return null
    }
}

/** Inbox card for engineering_analytics CI signals (flaky check, broken master, duration regression). */
export function EngineeringAnalyticsSignalCard({ signal }: SignalCardProps): JSX.Element {
    if (!hasRepoWorkflow(signal.extra)) {
        return <SignalCardShell signal={signal}>{null}</SignalCardShell>
    }
    const { repo_owner, repo_name, workflow_name } = signal.extra

    return (
        <SignalCardShell signal={signal}>
            <div className="flex flex-wrap items-center gap-2">
                <LemonTag size="small" icon={<IconGithub />}>
                    {repo_owner}/{repo_name}
                </LemonTag>
                <span className="font-medium">{workflow_name}</span>
                <MetricTag signal={signal} />
            </div>

            {signal.content && (
                <LemonMarkdown className="text-sm text-secondary mt-2" disableImages>
                    {signal.content}
                </LemonMarkdown>
            )}
        </SignalCardShell>
    )
}

export const engineeringAnalyticsSignalCardEntry: SignalCardEntry = {
    key: 'engineering_analytics',
    matches: (signal: SignalNode) => signal.source_product === 'engineering_analytics',
    Component: EngineeringAnalyticsSignalCard,
}
