import { useValues } from 'kea'

import { IconCheckCircle, IconPlay, IconWarning } from '@posthog/icons'
import { LemonTable } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { agentApplicationLogic } from '../agentApplicationLogic'
import type {
    AgentApplicationRevisionApi,
    AgentApplicationSessionApi,
    AgentApplicationSessionStateEnumApi,
} from '../generated/api.schemas'

const REVISION_STATE_CLASS: Record<string, string> = {
    pending_upload: 'as-pill as-pill-muted',
    uploaded: 'as-pill as-pill-muted',
    validating: 'as-pill as-pill-warning',
    ready: 'as-pill as-pill-live',
    failed: 'as-pill as-pill-danger',
}

const DEPLOYMENT_CLASS: Record<string, string> = {
    live: 'as-pill as-pill-live',
    preview: 'as-pill as-pill-preview',
    disabled: 'as-pill as-pill-muted',
}

const SESSION_CLASS: Record<AgentApplicationSessionStateEnumApi, string> = {
    available: 'as-pill as-pill-muted',
    running: 'as-pill as-pill-warning',
    completed: 'as-pill as-pill-live',
    failed: 'as-pill as-pill-danger',
    canceled: 'as-pill as-pill-muted',
}

const SESSION_ICON: Record<AgentApplicationSessionStateEnumApi, JSX.Element | null> = {
    available: null,
    running: <IconPlay />,
    completed: <IconCheckCircle />,
    failed: <IconWarning />,
    canceled: null,
}

function RevisionsStrip(): JSX.Element {
    const { revisions, revisionsLoading } = useValues(agentApplicationLogic)

    if (revisionsLoading && revisions.length === 0) {
        return (
            <div className="as-mono text-xs" style={{ color: 'var(--as-text-dim)' }}>
                syncing revisions…
            </div>
        )
    }

    if (revisions.length === 0) {
        return (
            <div className="as-mono text-xs italic" style={{ color: 'var(--as-text-dim)' }}>
                // no revisions deployed yet
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-3">
            <div className="flex items-center justify-between">
                <div className="as-label">▌ Recent revisions</div>
                <div className="as-mono text-xs" style={{ color: 'var(--as-text-dim)' }}>
                    showing {Math.min(revisions.length, 8)} of {revisions.length}
                </div>
            </div>
            <div className="flex flex-wrap gap-2">
                {revisions.slice(0, 8).map((rev: AgentApplicationRevisionApi) => (
                    <div key={rev.id} className="as-revision">
                        <span className="as-revision-hash">{rev.id.slice(0, 7)}</span>
                        <span className={REVISION_STATE_CLASS[rev.state] ?? 'as-pill as-pill-muted'}>{rev.state}</span>
                        {rev.deployment_status !== 'disabled' && (
                            <span className={DEPLOYMENT_CLASS[rev.deployment_status]}>{rev.deployment_status}</span>
                        )}
                        <span style={{ color: 'var(--as-text-dim)' }}>
                            <TZLabel time={rev.created_at} />
                        </span>
                    </div>
                ))}
            </div>
        </div>
    )
}

function SessionsTable(): JSX.Element {
    const { sessions, sessionsLoading } = useValues(agentApplicationLogic)

    return (
        <div className="flex flex-col gap-3">
            <div className="flex items-center justify-between">
                <div className="as-label">▌ Session activity</div>
                {!sessionsLoading && (
                    <div className="as-mono text-xs" style={{ color: 'var(--as-text-dim)' }}>
                        {sessions.length} {sessions.length === 1 ? 'event' : 'events'}
                    </div>
                )}
            </div>
            <div className="as-sessions">
                <LemonTable
                    loading={sessionsLoading}
                    dataSource={sessions}
                    emptyState={
                        <div className="py-8 text-center as-mono text-xs" style={{ color: 'var(--as-text-dim)' }}>
                            // no session activity yet
                        </div>
                    }
                    columns={[
                        {
                            title: 'State',
                            width: 140,
                            render: (_, session: AgentApplicationSessionApi) => (
                                <span className={SESSION_CLASS[session.state]}>
                                    {SESSION_ICON[session.state]}
                                    {session.state}
                                </span>
                            ),
                        },
                        {
                            title: 'Trigger',
                            render: (_, session: AgentApplicationSessionApi) =>
                                session.trigger_type ? (
                                    <span className="as-mono" style={{ color: 'var(--as-text)' }}>
                                        {session.trigger_type}
                                    </span>
                                ) : (
                                    <span style={{ color: 'var(--as-text-dim)' }}>–</span>
                                ),
                        },
                        {
                            title: 'Revision',
                            render: (_, session: AgentApplicationSessionApi) => (
                                <span className="as-mono" style={{ color: 'var(--as-text-muted)' }}>
                                    {session.revision.slice(0, 7)}
                                </span>
                            ),
                        },
                        {
                            title: 'Heartbeat',
                            render: (_, session: AgentApplicationSessionApi) =>
                                session.last_heartbeat_at ? (
                                    <span style={{ color: 'var(--as-text-muted)' }}>
                                        <TZLabel time={session.last_heartbeat_at} />
                                    </span>
                                ) : (
                                    <span style={{ color: 'var(--as-text-dim)' }}>–</span>
                                ),
                        },
                        {
                            title: 'Started',
                            render: (_, session: AgentApplicationSessionApi) => (
                                <span style={{ color: 'var(--as-text-muted)' }}>
                                    <TZLabel time={session.started_at ?? session.created_at} />
                                </span>
                            ),
                        },
                    ]}
                />
            </div>
        </div>
    )
}

export function AgentApplicationOverview(): JSX.Element {
    const { application } = useValues(agentApplicationLogic)

    return (
        <div className="flex flex-col gap-6">
            {application?.description && (
                <p className="text-sm max-w-3xl my-0" style={{ color: 'var(--as-text-muted)' }}>
                    {application.description}
                </p>
            )}
            <RevisionsStrip />
            <SessionsTable />
            <div className="as-mono text-xs" style={{ color: 'var(--as-text-dim)' }}>
                // session detail view shipping next · use <code>ass logs --follow</code> meanwhile
            </div>
        </div>
    )
}
