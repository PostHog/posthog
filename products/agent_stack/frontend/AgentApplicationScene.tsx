import './AgentStack.scss'

import { useActions, useValues } from 'kea'

import { IconLock } from '@posthog/icons'
import { LemonSkeleton, Link } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { agentApplicationLogic, AgentApplicationLogicProps, AgentApplicationTab } from './agentApplicationLogic'
import { AgentApplicationOverview } from './components/AgentApplicationOverview'
import { AgentApplicationSettings } from './components/AgentApplicationSettings'

export const scene: SceneExport<AgentApplicationLogicProps> = {
    component: AgentApplicationScene,
    logic: agentApplicationLogic,
    paramsToProps: ({ params: { slug } }) => ({ slug }),
}

function Telemetry(): JSX.Element {
    const { application, liveRevision } = useValues(agentApplicationLogic)
    const envCount = application?.env_redacted ? application.env_redacted.split('\n').filter(Boolean).length : 0

    return (
        <div className="as-telemetry">
            <div className="as-telemetry-cell">
                <div className="as-telemetry-label">// Live revision</div>
                <div className="as-telemetry-value">
                    {liveRevision ? (
                        <>
                            <span className="as-pulse" />
                            <span>{liveRevision.id.slice(0, 8)}</span>
                        </>
                    ) : (
                        <span style={{ color: 'var(--as-text-dim)' }}>none</span>
                    )}
                </div>
                <div className="as-telemetry-meta">
                    {liveRevision ? <span>state: {liveRevision.state}</span> : <span>no live deployment</span>}
                </div>
            </div>

            <div className="as-telemetry-cell">
                <div className="as-telemetry-label">// Secrets</div>
                <div className="as-telemetry-value">
                    <IconLock style={{ color: 'var(--as-text-muted)' }} />
                    {envCount}
                </div>
                <div className="as-telemetry-meta">
                    <span>encrypted · in-cluster decrypt only</span>
                </div>
            </div>

            <div className="as-telemetry-cell">
                <div className="as-telemetry-label">// Updated</div>
                <div className="as-telemetry-value" style={{ fontSize: 13, fontWeight: 400 }}>
                    {application ? new Date(application.updated_at).toISOString().slice(0, 19).replace('T', ' ') : ''}
                </div>
                <div className="as-telemetry-meta">utc · last manifest change</div>
            </div>
        </div>
    )
}

export function AgentApplicationScene(): JSX.Element {
    const { application, applicationLoading, applicationMissing, activeTab } = useValues(agentApplicationLogic)
    const { setActiveTab } = useActions(agentApplicationLogic)

    if (applicationMissing) {
        return <NotFound object="agent application" />
    }

    if (applicationLoading && !application) {
        return (
            <div className="agent-stack-console">
                <LemonSkeleton className="h-8 w-64 mb-4" />
                <LemonSkeleton className="h-24 w-full" />
            </div>
        )
    }

    if (!application) {
        return <NotFound object="agent application" />
    }

    return (
        <div className="agent-stack-console">
            <div className="as-hero">
                <div className="as-breadcrumb">
                    <Link to={urls.agentApplications()}>// agents</Link>
                    <span style={{ color: 'var(--as-text-dim)' }}> / {application.slug}</span>
                </div>
                <div className="flex items-end justify-between gap-3 flex-wrap mb-4">
                    <div className="flex flex-col gap-1">
                        <h1 className="as-hero-title">{application.name}</h1>
                        <code className="as-hero-subdomain">
                            {application.slug}
                            <span style={{ color: 'var(--as-text-dim)' }}>.agents.posthog.com</span>
                        </code>
                    </div>
                    <span className="as-pill as-pill-live">
                        <span className="as-pulse" style={{ width: 6, height: 6 }} />
                        Online
                    </span>
                </div>
            </div>

            <Telemetry />

            <div className="mt-6">
                <div className="as-tabs">
                    <button
                        className={`as-tab ${activeTab === AgentApplicationTab.Overview ? 'as-tab-active' : ''}`}
                        onClick={() => setActiveTab(AgentApplicationTab.Overview)}
                    >
                        ▌ Overview
                    </button>
                    <button
                        className={`as-tab ${activeTab === AgentApplicationTab.Settings ? 'as-tab-active' : ''}`}
                        onClick={() => setActiveTab(AgentApplicationTab.Settings)}
                    >
                        ▌ Settings
                    </button>
                </div>

                {activeTab === AgentApplicationTab.Overview ? (
                    <AgentApplicationOverview />
                ) : (
                    <AgentApplicationSettings />
                )}
            </div>
        </div>
    )
}
