import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconBolt, IconLock, IconPlay, IconPulse, IconTerminal, IconUnlock } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { agentApplicationLogic } from '../agentApplicationLogic'

function ToolChip({ name }: { name: string }): JSX.Element {
    const isBuiltIn = name.includes('@')
    return (
        <div
            className="as-revision"
            style={{ borderColor: isBuiltIn ? 'var(--as-border-strong)' : 'var(--as-border-accent)' }}
        >
            <IconBolt style={{ color: isBuiltIn ? 'var(--as-text-muted)' : 'var(--as-live)', width: 12, height: 12 }} />
            <span className="as-revision-hash">{name}</span>
            <span className="as-pill as-pill-muted" style={{ fontSize: 8, padding: '1px 5px' }}>
                {isBuiltIn ? 'built-in' : 'local'}
            </span>
        </div>
    )
}

function TriggerChip({ trigger }: { trigger: { id: string; type: string } }): JSX.Element {
    const typeColor: Record<string, string> = {
        http_invoke: 'var(--as-accent)',
        slack_event: 'var(--as-preview)',
        cron: 'var(--as-warning)',
    }
    return (
        <div className="as-revision">
            <IconPlay style={{ color: typeColor[trigger.type] ?? 'var(--as-text-muted)', width: 12, height: 12 }} />
            <span className="as-revision-hash">{trigger.id}</span>
            <span className="as-pill as-pill-muted" style={{ fontSize: 8, padding: '1px 5px' }}>
                {trigger.type}
            </span>
        </div>
    )
}

export function AgentConfigPanel(): JSX.Element | null {
    const { agentConfig, activeRevision } = useValues(agentApplicationLogic)
    const { promoteRevision } = useActions(agentApplicationLogic)
    const [promptExpanded, setPromptExpanded] = useState(false)

    if (!agentConfig || !activeRevision) {
        return null
    }

    const isLive = activeRevision.deployment_status === 'live'
    const isReady = activeRevision.state === 'ready'
    const canPromote = !isLive && isReady

    const promptPreview =
        agentConfig.prompt.length > 200 && !promptExpanded ? agentConfig.prompt.slice(0, 200) + '…' : agentConfig.prompt

    return (
        <div className="flex flex-col gap-5">
            {/* Header */}
            <div className="flex items-center justify-between flex-wrap gap-2">
                <div className="flex items-center gap-3">
                    <div className="as-label">▌ Agent configuration</div>
                    <span className={isLive ? 'as-pill as-pill-live' : 'as-pill as-pill-muted'} style={{ fontSize: 9 }}>
                        {isLive && <IconPulse style={{ width: 10, height: 10 }} />}
                        rev {activeRevision.id.slice(0, 8)}
                        {isLive ? ' · live' : ` · ${activeRevision.deployment_status}`}
                    </span>
                    <span className="as-pill as-pill-muted" style={{ fontSize: 9 }}>
                        {agentConfig.visibility === 'public' ? (
                            <IconUnlock style={{ width: 10, height: 10 }} />
                        ) : (
                            <IconLock style={{ width: 10, height: 10 }} />
                        )}
                        {agentConfig.visibility}
                    </span>
                </div>
                {canPromote && (
                    <LemonButton type="primary" size="small" onClick={() => promoteRevision(activeRevision.id)}>
                        Deploy this revision
                    </LemonButton>
                )}
            </div>

            {/* Prompt */}
            <div className="flex flex-col gap-2">
                <div className="as-label flex items-center gap-2">
                    <IconTerminal style={{ width: 12, height: 12 }} />
                    // System prompt
                </div>
                <div
                    className="as-env-readout cursor-pointer"
                    style={{
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word',
                        maxHeight: promptExpanded ? 'none' : '180px',
                        overflow: 'hidden',
                        position: 'relative',
                    }}
                    onClick={() => setPromptExpanded(!promptExpanded)}
                >
                    {promptPreview}
                    {agentConfig.prompt.length > 200 && !promptExpanded && (
                        <div
                            style={{
                                position: 'absolute',
                                bottom: 0,
                                left: 0,
                                right: 0,
                                height: '48px',
                                background: 'linear-gradient(transparent, var(--as-surface))',
                                display: 'flex',
                                alignItems: 'flex-end',
                                justifyContent: 'center',
                                paddingBottom: '4px',
                            }}
                        >
                            <span className="as-mono text-xs" style={{ color: 'var(--as-accent)' }}>
                                click to expand
                            </span>
                        </div>
                    )}
                </div>
                {promptExpanded && agentConfig.prompt.length > 200 && (
                    <button
                        className="as-mono text-xs self-start"
                        style={{
                            color: 'var(--as-accent)',
                            background: 'none',
                            border: 'none',
                            cursor: 'pointer',
                            padding: 0,
                        }}
                        onClick={() => setPromptExpanded(false)}
                    >
                        collapse
                    </button>
                )}
            </div>

            {/* Tools */}
            {agentConfig.tools.length > 0 && (
                <div className="flex flex-col gap-2">
                    <div className="as-label">
                        <IconBolt style={{ width: 12, height: 12, display: 'inline', marginRight: 6 }} />
                        // Tools ({agentConfig.tools.length})
                    </div>
                    <div className="flex flex-wrap gap-2">
                        {agentConfig.tools.map((tool) => (
                            <ToolChip key={tool} name={tool} />
                        ))}
                    </div>
                </div>
            )}

            {/* Triggers */}
            {agentConfig.triggers.length > 0 && (
                <div className="flex flex-col gap-2">
                    <div className="as-label">
                        <IconPlay style={{ width: 12, height: 12, display: 'inline', marginRight: 6 }} />
                        // Triggers ({agentConfig.triggers.length})
                    </div>
                    <div className="flex flex-wrap gap-2">
                        {agentConfig.triggers.map((trigger) => (
                            <TriggerChip key={trigger.id} trigger={trigger} />
                        ))}
                    </div>
                </div>
            )}

            {/* Empty states */}
            {agentConfig.tools.length === 0 && agentConfig.triggers.length === 0 && (
                <div className="as-mono text-xs" style={{ color: 'var(--as-text-dim)' }}>
                    // no tools or triggers configured
                </div>
            )}
        </div>
    )
}
