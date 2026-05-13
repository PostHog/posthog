import { useValues } from 'kea'

import { LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { csmHudSceneLogic, FleetRow } from '../logics/csmHudSceneLogic'
import { AccountActivity } from '../queries/activity'
import { conversations } from '../utils/engagement'
import { formatMoneyCompact } from '../utils/format'
import { ProjectionRow } from '../utils/projection'

interface ConversationsRow {
    account: FleetRow
    openCount: number
    urgentCount: number
    latestSubject: string | null
    oldestOpenDate: string | null
    arr: number | null
}

type BandId = 'critical' | 'many' | 'few' | 'quiet'

function bandFor(open: number, urgent: number): BandId {
    if (urgent > 0) {
        return 'critical'
    }
    if (open >= 4) {
        return 'many'
    }
    if (open >= 1) {
        return 'few'
    }
    return 'quiet'
}

const BAND_LABELS: Record<BandId, string> = {
    critical: 'Critical · urgent open',
    many: 'Many · 4+ open',
    few: 'Few · 1–3 open',
    quiet: 'Quiet · 0 open',
}

function buildRows(
    fleet: FleetRow[],
    activity: Record<string, AccountActivity>,
    projection: Record<string, ProjectionRow>
): ConversationsRow[] {
    return fleet.map((account) => {
        const c = conversations(activity[account.externalId])
        return {
            account,
            openCount: c.openCount,
            urgentCount: c.urgentCount,
            latestSubject: c.latest?.subject ?? null,
            oldestOpenDate: c.oldestOpen?.createdAt ?? null,
            arr: projection[account.externalId]?.arrDiscounted ?? null,
        }
    })
}

function ConversationsBand({ label, rows }: { label: string; rows: ConversationsRow[] }): JSX.Element | null {
    if (rows.length === 0) {
        return null
    }
    return (
        <section>
            <h3 className="text-base font-medium mb-2">
                {label} · {rows.length}
            </h3>
            <LemonTable<ConversationsRow>
                dataSource={rows}
                rowKey={(r) => r.account.id}
                columns={[
                    {
                        title: 'Account',
                        key: 'name',
                        render: (_, r) => (
                            <Link to={urls.csmHudCustomer(r.account.externalId)} className="font-medium">
                                {r.account.name}
                            </Link>
                        ),
                        sorter: (a, b) => a.account.name.localeCompare(b.account.name),
                    },
                    {
                        title: 'Open',
                        key: 'open',
                        align: 'right',
                        render: (_, r) => r.openCount.toLocaleString(),
                        sorter: (a, b) => a.openCount - b.openCount,
                    },
                    {
                        title: 'Urgent',
                        key: 'urgent',
                        align: 'right',
                        render: (_, r) =>
                            r.urgentCount > 0 ? (
                                <LemonTag type="danger">{r.urgentCount}</LemonTag>
                            ) : (
                                <span className="text-muted">0</span>
                            ),
                        sorter: (a, b) => a.urgentCount - b.urgentCount,
                    },
                    {
                        title: 'Latest',
                        key: 'latest',
                        render: (_, r) => r.latestSubject ?? '—',
                    },
                    {
                        title: 'Oldest open',
                        key: 'oldestOpen',
                        render: (_, r) => r.oldestOpenDate?.slice(0, 10) ?? '—',
                    },
                    {
                        title: 'ARR',
                        key: 'arr',
                        align: 'right',
                        render: (_, r) => formatMoneyCompact(r.arr),
                        sorter: (a, b) => (a.arr ?? 0) - (b.arr ?? 0),
                    },
                ]}
            />
        </section>
    )
}

export function ConversationsTab(): JSX.Element {
    const { fleet, projection, activity, activityLoading } = useValues(csmHudSceneLogic)
    const rows = buildRows(fleet, activity, projection)
    const byBand: Record<BandId, ConversationsRow[]> = { critical: [], many: [], few: [], quiet: [] }
    for (const r of rows) {
        byBand[bandFor(r.openCount, r.urgentCount)].push(r)
    }
    const totalOpen = rows.reduce((sum, r) => sum + r.openCount, 0)
    const totalUrgent = rows.reduce((sum, r) => sum + r.urgentCount, 0)
    const tracked = rows.filter((r) => r.account.traits['zendesk.id'] != null).length

    return (
        <div className="space-y-4">
            <div className="text-muted text-sm">
                {totalOpen} open · {totalUrgent} urgent · {tracked} accounts tracked
            </div>
            {fleet.length === 0 ? (
                <div className="text-muted py-8 text-center">
                    Conversations requires fleet rows. Load is empty on this team.
                </div>
            ) : activityLoading && Object.keys(activity).length === 0 ? (
                <div className="text-muted py-8 text-center">Loading recent tickets…</div>
            ) : (
                (Object.keys(BAND_LABELS) as BandId[]).map((id) => (
                    <ConversationsBand key={id} label={BAND_LABELS[id]} rows={byBand[id]} />
                ))
            )}
        </div>
    )
}
