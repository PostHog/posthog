import './AgentStack.scss'

import { useValues } from 'kea'
import { router } from 'kea-router'

import { IconArrowRight, IconBolt } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { agentApplicationsLogic } from './agentApplicationsLogic'
import type { AgentApplicationApi } from './generated/api.schemas'

export const scene: SceneExport = {
    component: AgentApplicationsScene,
    logic: agentApplicationsLogic,
}

function countEnvKeys(envRedacted: string): number {
    if (!envRedacted) {
        return 0
    }
    return envRedacted.split('\n').filter((line) => line.trim().length > 0).length
}

function TelemetryHeader({ apps }: { apps: AgentApplicationApi[] }): JSX.Element {
    const totalEnv = apps.reduce((acc, a) => acc + countEnvKeys(a.env_redacted), 0)
    return (
        <div className="as-telemetry mb-6">
            <div className="as-telemetry-cell">
                <div className="as-telemetry-label">// Agents online</div>
                <div className="as-telemetry-value">
                    <span className="as-pulse" />
                    {apps.length.toString().padStart(2, '0')}
                </div>
                <div className="as-telemetry-meta">tracking via posthog · realtime</div>
            </div>
            <div className="as-telemetry-cell">
                <div className="as-telemetry-label">// Secrets registered</div>
                <div className="as-telemetry-value">{totalEnv}</div>
                <div className="as-telemetry-meta">across {apps.length} agents</div>
            </div>
            <div className="as-telemetry-cell">
                <div className="as-telemetry-label">// Console build</div>
                <div className="as-telemetry-value as-mono">v0.1.0-alpha</div>
                <div className="as-telemetry-meta">operator: console</div>
            </div>
        </div>
    )
}

function ApplicationCard({ app, index }: { app: AgentApplicationApi; index: number }): JSX.Element {
    const detailUrl = urls.agentApplication(app.slug)
    const envCount = countEnvKeys(app.env_redacted)

    return (
        <div
            className="as-card as-card-live"
            onClick={() => router.actions.push(detailUrl)}
            style={{ animationDelay: `${index * 40}ms` }}
        >
            <div className="flex items-start justify-between gap-3">
                <div className="flex flex-col gap-1 min-w-0">
                    <div className="flex items-center gap-2">
                        <span className="as-pulse" />
                        <span className="as-label as-label-accent">// Live</span>
                    </div>
                    <h3
                        className="text-lg font-semibold truncate"
                        style={{ color: 'var(--as-text-bright)', fontFamily: 'var(--as-display)', margin: 0 }}
                    >
                        {app.name}
                    </h3>
                    <code className="as-mono text-xs" style={{ color: 'var(--as-text-muted)' }}>
                        {app.slug}
                        <span style={{ color: 'var(--as-text-dim)' }}>.agents.posthog.com</span>
                    </code>
                </div>
                <IconArrowRight style={{ color: 'var(--as-text-dim)' }} className="mt-1 shrink-0" />
            </div>

            <p
                className="text-xs leading-relaxed my-0 line-clamp-2"
                style={{ color: app.description ? 'var(--as-text-muted)' : 'var(--as-text-dim)' }}
            >
                {app.description || '// no description set'}
            </p>

            <div className="mt-auto flex flex-col gap-2">
                <div className="as-divider" />
                <div className="flex items-center justify-between as-mono text-xs">
                    <div className="flex items-center gap-3" style={{ color: 'var(--as-text-muted)' }}>
                        <span>
                            <span style={{ color: 'var(--as-text)' }}>{envCount}</span>
                            <span style={{ color: 'var(--as-text-dim)' }}> env</span>
                        </span>
                        <span className="as-dot">·</span>
                        <span>
                            <span style={{ color: 'var(--as-text)' }}>—</span>
                            <span style={{ color: 'var(--as-text-dim)' }}> sessions</span>
                        </span>
                    </div>
                    <span style={{ color: 'var(--as-text-dim)' }}>
                        <TZLabel time={app.updated_at} />
                    </span>
                </div>
            </div>
        </div>
    )
}

function EmptyState(): JSX.Element {
    return (
        <div className="as-empty">
            <div className="as-label as-label-accent mb-4">// No deployments detected</div>
            <h3
                className="text-xl font-semibold m-0 mb-2"
                style={{ color: 'var(--as-text-bright)', fontFamily: 'var(--as-display)' }}
            >
                The console is waiting.
            </h3>
            <p className="text-sm m-0 mb-6 mx-auto max-w-md" style={{ color: 'var(--as-text-muted)' }}>
                Scaffold an agent with <code className="as-mono">ass new my-agent</code>, then{' '}
                <code className="as-mono">ass deploy</code> to bring it online.
            </p>
            <LemonButton
                type="primary"
                icon={<IconBolt />}
                onClick={() => window.open('https://github.com/PostHog/agent-stack', '_blank')}
            >
                Open the docs
            </LemonButton>
        </div>
    )
}

export function AgentApplicationsScene(): JSX.Element {
    const { applications, applicationsLoading } = useValues(agentApplicationsLogic)
    const shouldShowEmpty = applications.length === 0 && !applicationsLoading

    return (
        <div className="agent-stack-console">
            <div className="as-hero mb-6">
                <div className="as-breadcrumb">// agents</div>
                <h1 className="as-hero-title">Agent stack</h1>
                <p className="as-mono text-xs m-0" style={{ color: 'var(--as-text-muted)' }}>
                    operator console · monitoring deployed agents in real time
                </p>
            </div>

            {!shouldShowEmpty && <TelemetryHeader apps={applications} />}

            <div className="flex items-center justify-between mb-3">
                <div className="as-label">▌ Deployed agents</div>
                <div className="as-mono text-xs" style={{ color: 'var(--as-text-dim)' }}>
                    {applicationsLoading ? 'syncing…' : `${applications.length} active`}
                </div>
            </div>

            {shouldShowEmpty ? (
                <EmptyState />
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                    {applications.map((app, i) => (
                        <ApplicationCard key={app.id} app={app} index={i} />
                    ))}
                </div>
            )}
        </div>
    )
}
