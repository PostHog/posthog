import { useValues } from 'kea'

import { LemonTable, LemonTag } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport, SceneParams } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { customerDetailLogic, CustomerDetailLogicProps } from '../logics/customerDetailLogic'
import { Note, Task, Ticket, TopUser } from '../queries/customer'
import { formatMoney } from '../utils/format'
import { healthBand, healthLabel } from '../utils/health'
import { deriveProjection, ProjectionRow } from '../utils/projection'

const HEALTH_TAG_TYPE: Record<ReturnType<typeof healthBand>, 'success' | 'warning' | 'danger' | 'default'> = {
    good: 'success',
    ok: 'warning',
    bad: 'danger',
    unknown: 'default',
}

export const scene: SceneExport<CustomerDetailLogicProps> = {
    component: CSMHudCustomerScene,
    logic: customerDetailLogic,
    paramsToProps: ({ params }: SceneParams): CustomerDetailLogicProps => ({
        externalId: decodeURIComponent(params.externalId ?? ''),
    }),
}

function ProjectionMath({ p }: { p: ProjectionRow }): JSX.Element {
    const derived = deriveProjection(p)
    const rows: [string, string][] = [
        ['M1 prior month MRR', formatMoney(p.priorMonthMrr)],
        ['M2 actual', formatMoney(p.m2Actual)],
        ['M3 actual', formatMoney(p.m3Actual)],
        ['Weighted baseline', `${formatMoney(p.weightedBaseline)} (renormalized over ${p.historyMonths}/3 mo)`],
        ['Daily rate', `${formatMoney(derived.dailyRate)}/d (over ${derived.daysInCurrentMonth}d)`],
        ['MTD spend', formatMoney(p.currentMonthSpend)],
        ['Days remaining', `${derived.daysRemaining}d`],
        ['Forecasted EoM', formatMoney(p.forecastedMrr)],
    ]
    return (
        <table className="text-sm">
            <tbody>
                {rows.map(([label, value]) => (
                    <tr key={label}>
                        <td className="text-muted pr-4">{label}</td>
                        <td className="font-medium">{value}</td>
                    </tr>
                ))}
            </tbody>
        </table>
    )
}

function TopUsersSection({ users, loading }: { users: TopUser[]; loading: boolean }): JSX.Element {
    return (
        <LemonTable<TopUser>
            loading={loading}
            dataSource={users}
            rowKey="email"
            columns={[
                {
                    title: 'User',
                    key: 'user',
                    render: (_, u) => (
                        <div>
                            <div className="font-medium">{u.userName || u.email}</div>
                            <div className="text-muted text-xs">{u.email}</div>
                        </div>
                    ),
                },
                { title: 'Role', key: 'role', render: (_, u) => u.role || '—' },
                {
                    title: 'Sessions (30d)',
                    key: 'sessions',
                    align: 'right',
                    render: (_, u) => u.sessions.toLocaleString(),
                },
                {
                    title: 'Last seen',
                    key: 'lastSeen',
                    render: (_, u) => (u.lastSeen ? u.lastSeen.slice(0, 10) : '—'),
                },
            ]}
            emptyState={<div className="text-muted py-4 text-center">No top-user data.</div>}
        />
    )
}

function TicketsSection({ tickets, loading }: { tickets: Ticket[]; loading: boolean }): JSX.Element {
    return (
        <LemonTable<Ticket>
            loading={loading}
            dataSource={tickets}
            rowKey={(t) => `${t.createdAt}-${t.subject}`}
            columns={[
                { title: 'Subject', key: 'subject', render: (_, t) => t.subject },
                {
                    title: 'Status',
                    key: 'status',
                    render: (_, t) => <LemonTag>{t.status}</LemonTag>,
                },
                { title: 'Priority', key: 'priority', render: (_, t) => t.priority ?? '—' },
                {
                    title: 'Created',
                    key: 'created',
                    render: (_, t) => t.createdAt.slice(0, 10),
                },
            ]}
            emptyState={<div className="text-muted py-4 text-center">No recent Zendesk tickets.</div>}
        />
    )
}

function NotesSection({ notes, loading }: { notes: Note[]; loading: boolean }): JSX.Element {
    return (
        <LemonTable<Note>
            loading={loading}
            dataSource={notes}
            rowKey="id"
            columns={[
                { title: 'Date', key: 'date', render: (_, n) => n.noteDate?.slice(0, 10) ?? '—' },
                { title: 'Subject', key: 'subject', render: (_, n) => n.subject || '—' },
                { title: 'Author', key: 'author', render: (_, n) => n.author || '—' },
                { title: 'Category', key: 'category', render: (_, n) => n.category || '—' },
            ]}
            emptyState={<div className="text-muted py-4 text-center">No recent notes.</div>}
        />
    )
}

function TasksSection({ tasks, loading }: { tasks: Task[]; loading: boolean }): JSX.Element {
    return (
        <LemonTable<Task>
            loading={loading}
            dataSource={tasks}
            rowKey="id"
            columns={[
                { title: 'Due', key: 'due', render: (_, t) => t.dueDate?.slice(0, 10) ?? '—' },
                { title: 'Name', key: 'name', render: (_, t) => t.name || '—' },
                {
                    title: 'Status',
                    key: 'status',
                    render: (_, t) => (t.completedAt ? 'done' : 'open'),
                },
            ]}
            emptyState={<div className="text-muted py-4 text-center">No open tasks.</div>}
        />
    )
}

export function CSMHudCustomerScene(): JSX.Element {
    const {
        account,
        accountProjection,
        fleetLoading,
        topUsers,
        topUsersLoading,
        tickets,
        ticketsLoading,
        notes,
        notesLoading,
        tasks,
        tasksLoading,
    } = useValues(customerDetailLogic)

    const { user } = useValues(userLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const canAccess =
        !!featureFlags[FEATURE_FLAGS.SCENE_CSM_HUD] && !!user?.is_staff && !!user?.email?.endsWith('@posthog.com')

    if (!canAccess) {
        return <NotFound object="page" />
    }

    if (!account && !fleetLoading) {
        return <NotFound object="customer" />
    }

    const band = healthBand(account?.healthScore ?? null)

    return (
        <SceneContent>
            <SceneTitleSection
                name={account?.name ?? '—'}
                description={account ? `External ID: ${account.externalId}` : 'Loading account…'}
                resourceType={{ type: 'csm_hud' }}
            />
            <div className="flex items-center gap-2">
                <LemonTag type={HEALTH_TAG_TYPE[band]}>
                    Health {account?.healthScore != null ? account.healthScore.toFixed(1) : '—'} ·{' '}
                    {healthLabel(account?.healthScore ?? null)}
                </LemonTag>
                {accountProjection?.csm && <LemonTag>CSM · {accountProjection.csm}</LemonTag>}
                {accountProjection?.ae && <LemonTag>AE · {accountProjection.ae}</LemonTag>}
            </div>

            {accountProjection ? (
                <section>
                    <h3 className="text-base font-medium mb-2">Projection math</h3>
                    <ProjectionMath p={accountProjection} />
                </section>
            ) : (
                <p className="text-muted">Projection unavailable for this account on this team.</p>
            )}

            <section>
                <h3 className="text-base font-medium mb-2">Top 5 users · sessions (30d)</h3>
                <TopUsersSection users={topUsers} loading={topUsersLoading} />
            </section>

            <section>
                <h3 className="text-base font-medium mb-2">Recent Zendesk tickets</h3>
                <TicketsSection tickets={tickets} loading={ticketsLoading} />
            </section>

            <section>
                <h3 className="text-base font-medium mb-2">Recent notes</h3>
                <NotesSection notes={notes} loading={notesLoading} />
            </section>

            <section>
                <h3 className="text-base font-medium mb-2">Open tasks</h3>
                <TasksSection tasks={tasks} loading={tasksLoading} />
            </section>
        </SceneContent>
    )
}

export default CSMHudCustomerScene
