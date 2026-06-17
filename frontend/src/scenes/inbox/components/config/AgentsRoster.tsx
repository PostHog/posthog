import { useActions, useValues } from 'kea'
import { memo, useCallback } from 'react'

import { IconArrowUpRight } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonSwitch, LemonTag, Link, Spinner } from '@posthog/lemon-ui'

import { LemonTagType } from 'lib/lemon-ui/LemonTag/LemonTag'

import { signalSourcesLogic } from '../../signalSourcesLogic'
import { SignalSourceConfig, SignalSourceConfigStatus } from '../../types'
import { getSourceProductMeta } from '../badges/sourceProductIcons'
import { AGENT_ROSTER_GROUPS, AgentRosterDefinition, AgentRosterSource } from './agentRosterMeta'

type AgentRosterStatus = 'standby' | 'watching' | 'syncing' | 'sync_failed'

const STATUS_TAG: Record<AgentRosterStatus, { label: string; type: LemonTagType }> = {
    standby: { label: 'Standby', type: 'muted' },
    watching: { label: 'Watching', type: 'success' },
    syncing: { label: 'Syncing', type: 'primary' },
    sync_failed: { label: 'Sync failed', type: 'danger' },
}

function resolveAgentStatus(
    armed: boolean,
    syncStatus: SignalSourceConfigStatus | null | undefined
): AgentRosterStatus {
    if (!armed) {
        return 'standby'
    }
    if (syncStatus === SignalSourceConfigStatus.RUNNING) {
        return 'syncing'
    }
    if (syncStatus === SignalSourceConfigStatus.FAILED) {
        return 'sync_failed'
    }
    return 'watching'
}

/** Per-source derived state assembled by `AgentsRoster` from `signalSourcesLogic`. */
interface AgentSourceState {
    armed: boolean
    loading: boolean
    /** True for data-warehouse sources that haven't been connected yet – shows a Connect button. */
    requiresSetup: boolean
    syncStatus: SignalSourceConfigStatus | null | undefined
}

function AgentIcon({ source }: { source: AgentRosterDefinition }): JSX.Element {
    const meta = getSourceProductMeta(source.sourceProduct)
    const Icon = meta?.Icon
    const color = meta?.color ?? 'var(--accent)'
    return (
        <div
            className="flex items-center justify-center size-8 shrink-0 rounded ring-1 ring-inset ring-primary"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ backgroundColor: `color-mix(in srgb, ${color} 12%, transparent)` }}
        >
            {/* eslint-disable-next-line react/forbid-dom-props */}
            {Icon ? <Icon className="size-[18px]" style={{ color }} /> : null}
        </div>
    )
}

interface AgentCardProps {
    agent: AgentRosterDefinition
    state: AgentSourceState
    onToggle: (source: AgentRosterSource) => void
}

const AgentCard = memo(function AgentCard({ agent, state, onToggle }: AgentCardProps): JSX.Element {
    const { armed, loading, requiresSetup, syncStatus } = state
    const status = resolveAgentStatus(armed, syncStatus)
    const statusTag = STATUS_TAG[status]
    const isInteractive = !loading

    const handleCardClick = useCallback(() => {
        if (!isInteractive) {
            return
        }
        onToggle(agent.source)
    }, [agent.source, isInteractive, onToggle])

    return (
        <div
            onClick={isInteractive ? handleCardClick : undefined}
            className={[
                'rounded border p-3 transition-colors',
                armed ? 'border-accent bg-accent-highlight-secondary' : 'border-primary bg-surface-primary',
                isInteractive ? 'cursor-pointer hover:border-secondary' : 'cursor-default',
            ].join(' ')}
        >
            <div className="flex items-start justify-between gap-3">
                <div className="flex items-start gap-3 min-w-0 flex-1">
                    <AgentIcon source={agent} />
                    <div className="flex flex-col gap-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                            <span className="font-medium text-sm text-default">{agent.label}</span>
                            {agent.alpha && (
                                <LemonTag type="completion" size="small">
                                    Alpha
                                </LemonTag>
                            )}
                        </div>
                        <p className="text-sm text-secondary leading-snug mb-0">{agent.description}</p>
                        {agent.docsUrl && (
                            <Link
                                to={agent.docsUrl}
                                target="_blank"
                                className="inline-flex items-center gap-1 text-sm w-fit"
                                onClick={(e) => e.stopPropagation()}
                            >
                                Learn about {agent.docsLabel ?? agent.label}
                                <IconArrowUpRight />
                            </Link>
                        )}
                    </div>
                </div>

                {/* eslint-disable-next-line react/no-unknown-property */}
                <div className="flex flex-col items-end gap-2 shrink-0" onClick={(e) => e.stopPropagation()}>
                    <LemonTag type={statusTag.type} size="small">
                        {statusTag.label}
                    </LemonTag>
                    {loading ? (
                        <Spinner className="text-lg" />
                    ) : requiresSetup ? (
                        <LemonButton type="primary" size="small" onClick={() => onToggle(agent.source)}>
                            Connect
                        </LemonButton>
                    ) : (
                        <LemonSwitch
                            checked={armed}
                            onChange={() => onToggle(agent.source)}
                            aria-label={`Arm ${agent.label}`}
                        />
                    )}
                </div>
            </div>

            {armed && agent.source === 'session_replay' && status === 'syncing' && (
                <div className="flex items-center gap-2 mt-2 ml-11">
                    <Spinner className="text-sm text-accent" />
                    <span className="text-sm text-accent">Session analysis run in progress…</span>
                </div>
            )}
        </div>
    )
})

export function AgentsRoster(): JSX.Element {
    const {
        sessionAnalysisConfig,
        conversationsConfig,
        githubIssuesConfig,
        linearIssuesConfig,
        zendeskTicketsConfig,
        pgAnalyzeIssuesConfig,
        errorTrackingIsFullyEnabled,
        isSessionAnalysisToggling,
        isConversationsToggling,
        isErrorTrackingToggling,
        isGithubIssuesToggling,
        isLinearIssuesToggling,
        isZendeskTicketsToggling,
        isPgAnalyzeIssuesToggling,
    } = useValues(signalSourcesLogic)
    const { toggleSessionAnalysis, toggleConversations, toggleErrorTracking, initiateDataWarehouseSourceToggle } =
        useActions(signalSourcesLogic)

    const stateFor = useCallback(
        (source: AgentRosterSource): AgentSourceState => {
            const dwState = (config: SignalSourceConfig | null, loading: boolean): AgentSourceState => ({
                armed: !!config?.enabled,
                loading,
                // No config row yet → the source has never been connected; surface a Connect button.
                requiresSetup: config === null,
                syncStatus: config?.status,
            })
            switch (source) {
                case 'error_tracking':
                    return {
                        armed: errorTrackingIsFullyEnabled,
                        loading: isErrorTrackingToggling,
                        requiresSetup: false,
                        syncStatus: null,
                    }
                case 'conversations':
                    return {
                        armed: !!conversationsConfig?.enabled,
                        loading: isConversationsToggling,
                        requiresSetup: false,
                        syncStatus: conversationsConfig?.status,
                    }
                case 'session_replay':
                    return {
                        armed: !!sessionAnalysisConfig?.enabled,
                        loading: isSessionAnalysisToggling,
                        requiresSetup: false,
                        syncStatus: sessionAnalysisConfig?.status,
                    }
                case 'github':
                    return dwState(githubIssuesConfig, isGithubIssuesToggling)
                case 'linear':
                    return dwState(linearIssuesConfig, isLinearIssuesToggling)
                case 'zendesk':
                    return dwState(zendeskTicketsConfig, isZendeskTicketsToggling)
                case 'pganalyze':
                    return dwState(pgAnalyzeIssuesConfig, isPgAnalyzeIssuesToggling)
            }
        },
        [
            errorTrackingIsFullyEnabled,
            isErrorTrackingToggling,
            conversationsConfig,
            isConversationsToggling,
            sessionAnalysisConfig,
            isSessionAnalysisToggling,
            githubIssuesConfig,
            isGithubIssuesToggling,
            linearIssuesConfig,
            isLinearIssuesToggling,
            zendeskTicketsConfig,
            isZendeskTicketsToggling,
            pgAnalyzeIssuesConfig,
            isPgAnalyzeIssuesToggling,
        ]
    )

    const handleToggle = useCallback(
        (source: AgentRosterSource) => {
            switch (source) {
                case 'error_tracking':
                    toggleErrorTracking()
                    return
                case 'conversations':
                    toggleConversations()
                    return
                case 'session_replay':
                    toggleSessionAnalysis()
                    return
                case 'github':
                    initiateDataWarehouseSourceToggle('Github')
                    return
                case 'linear':
                    initiateDataWarehouseSourceToggle('Linear')
                    return
                case 'zendesk':
                    initiateDataWarehouseSourceToggle('Zendesk')
                    return
                case 'pganalyze':
                    initiateDataWarehouseSourceToggle('PgAnalyze')
                    return
            }
        },
        [toggleErrorTracking, toggleConversations, toggleSessionAnalysis, initiateDataWarehouseSourceToggle]
    )

    return (
        <div className="flex flex-col gap-5">
            {AGENT_ROSTER_GROUPS.map((group) => (
                <div key={group.label} className="flex flex-col gap-2">
                    <span className="text-[13px] font-medium text-muted">{group.label}</span>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        {group.agents.map((agent) => (
                            <AgentCard
                                key={agent.source}
                                agent={agent}
                                state={stateFor(agent.source)}
                                onToggle={handleToggle}
                            />
                        ))}
                    </div>
                </div>
            ))}
        </div>
    )
}

function AgentCardSkeleton(): JSX.Element {
    return (
        <div className="rounded border border-primary bg-surface-primary p-3">
            <div className="flex items-start justify-between gap-3">
                <div className="flex items-start gap-3 min-w-0 flex-1">
                    <LemonSkeleton className="size-8 shrink-0 rounded" />
                    <div className="flex flex-col gap-2 min-w-0 flex-1">
                        <LemonSkeleton className="h-3 w-1/2" />
                        <LemonSkeleton className="h-3 w-1/3" />
                        <LemonSkeleton className="h-3 w-4/5" />
                    </div>
                </div>
                <LemonSkeleton className="h-5 w-16 shrink-0" />
            </div>
        </div>
    )
}

export function AgentsRosterSkeleton(): JSX.Element {
    return (
        <div className="flex flex-col gap-5">
            {AGENT_ROSTER_GROUPS.map((group) => (
                <div key={group.label} className="flex flex-col gap-2">
                    <LemonSkeleton className="h-3 w-24" />
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        {group.agents.map((agent) => (
                            <AgentCardSkeleton key={agent.source} />
                        ))}
                    </div>
                </div>
            ))}
        </div>
    )
}
