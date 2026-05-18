import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconPlay, IconWarning } from '@posthog/icons'
import { LemonTable } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { agentApplicationLogic, type AgentSession } from '../agentApplicationLogic'
import type { AgentApplicationRevisionApi } from '../generated/api.schemas'
import { AgentConfigPanel } from './AgentConfigPanel'
import { SessionLogsPanel } from './SessionLogsPanel'

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

function RevisionsStrip(): JSX.Element {
    const { revisions, revisionsLoading, selectedRevisionId, activeRevision } = useValues(agentApplicationLogic)
    const { selectRevision } = useActions(agentApplicationLogic)

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
                <div className="as-label">▌ Revisions — click to inspect</div>
                <div className="as-mono text-xs" style={{ color: 'var(--as-text-dim)' }}>
                    {selectedRevisionId ? (
                        <button
                            style={{
                                color: 'var(--as-accent)',
                                background: 'none',
                                border: 'none',
                                cursor: 'pointer',
                                padding: 0,
                                fontFamily: 'inherit',
                                fontSize: 'inherit',
                            }}
                            onClick={() => selectRevision(null)}
                        >
                            ← back to live
                        </button>
                    ) : (
                        `${revisions.length} total`
                    )}
                </div>
            </div>
            <div className="flex flex-wrap gap-2">
                {revisions.map((rev: AgentApplicationRevisionApi) => {
                    const isSelected = activeRevision?.id === rev.id
                    return (
                        <div
                            key={rev.id}
                            className="as-revision"
                            onClick={() => selectRevision(rev.id === selectedRevisionId ? null : rev.id)}
                            style={{
                                cursor: 'pointer',
                                borderColor: isSelected ? 'var(--as-accent)' : undefined,
                                background: isSelected ? 'rgba(56, 189, 248, 0.08)' : undefined,
                            }}
                        >
                            <span className="as-revision-hash">{rev.id.slice(0, 7)}</span>
                            <span className={REVISION_STATE_CLASS[rev.state] ?? 'as-pill as-pill-muted'}>
                                {rev.state}
                            </span>
                            {rev.deployment_status !== 'disabled' && (
                                <span className={DEPLOYMENT_CLASS[rev.deployment_status]}>{rev.deployment_status}</span>
                            )}
                            <span style={{ color: 'var(--as-text-dim)' }}>
                                <TZLabel time={rev.created_at} />
                            </span>
                        </div>
                    )
                })}
            </div>
        </div>
    )
}

const SESSION_STATUS_CLASS: Record<string, string> = {
    available: 'as-pill as-pill-muted',
    running: 'as-pill as-pill-warning',
    completed: 'as-pill as-pill-live',
    failed: 'as-pill as-pill-danger',
    canceled: 'as-pill as-pill-muted',
}

const SESSION_STATUS_ICON: Record<string, JSX.Element | null> = {
    running: <IconPlay style={{ width: 10, height: 10 }} />,
    completed: <IconCheckCircle style={{ width: 10, height: 10 }} />,
    failed: <IconWarning style={{ width: 10, height: 10 }} />,
    available: null,
    canceled: null,
}

function SessionsTable(): JSX.Element {
    const { sessions, sessionsLoading, application } = useValues(agentApplicationLogic)

    return (
        <div className="flex flex-col gap-3">
            <div className="flex items-center justify-between">
                <div className="as-label">▌ Sessions</div>
                {!sessionsLoading && (
                    <div className="as-mono text-xs" style={{ color: 'var(--as-text-dim)' }}>
                        {sessions.length} {sessions.length === 1 ? 'session' : 'sessions'}
                    </div>
                )}
            </div>
            <div className="as-sessions">
                <LemonTable
                    loading={sessionsLoading}
                    dataSource={sessions}
                    emptyState={
                        <div className="py-8 text-center as-mono text-xs" style={{ color: 'var(--as-text-dim)' }}>
                            // no sessions yet — trigger one via the ingress
                        </div>
                    }
                    expandable={{
                        expandedRowRender: (session: AgentSession) =>
                            application ? (
                                <SessionLogsPanel applicationSlug={application.slug} sessionId={session.id} />
                            ) : null,
                        noIndent: true,
                    }}
                    columns={[
                        {
                            title: 'Status',
                            width: 140,
                            render: (_, session: AgentSession) => (
                                <span className={SESSION_STATUS_CLASS[session.status] ?? 'as-pill as-pill-muted'}>
                                    {SESSION_STATUS_ICON[session.status]}
                                    {session.status}
                                </span>
                            ),
                        },
                        {
                            title: 'ID',
                            render: (_, session: AgentSession) => (
                                <code className="as-mono text-xs">{session.id.slice(0, 12)}…</code>
                            ),
                        },
                        {
                            title: 'Transitions',
                            render: (_, session: AgentSession) => (
                                <span className="as-mono text-xs">{session.transition_count}</span>
                            ),
                        },
                        {
                            title: 'Last activity',
                            render: (_, session: AgentSession) =>
                                session.last_transition ? (
                                    <TZLabel time={session.last_transition} />
                                ) : session.created ? (
                                    <TZLabel time={session.created} />
                                ) : (
                                    <span style={{ color: 'var(--as-text-dim)' }}>–</span>
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
            <AgentConfigPanel />
            <div className="as-divider" />
            <RevisionsStrip />
            <div className="as-divider" />
            <SessionsTable />
        </div>
    )
}
