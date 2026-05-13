import { useValues } from 'kea'

import { LemonTable, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { csmHudSceneLogic, FleetRow } from '../logics/csmHudSceneLogic'
import { AccountActivity } from '../queries/activity'
import { engagement } from '../utils/engagement'
import { formatMoneyCompact } from '../utils/format'
import { ProjectionRow } from '../utils/projection'

interface EngagementRow {
    account: FleetRow
    daysSinceLastTouch: number | null
    lastNoteDate: string | null
    lastTaskDate: string | null
    arr: number | null
}

const BANDS = [
    { id: 'fresh' as const, label: 'Fresh · ≤7d', max: 7 },
    { id: 'cooling' as const, label: 'Cooling · 8–21d', max: 21 },
    { id: 'cold' as const, label: 'Cold · 22–60d', max: 60 },
    { id: 'frozen' as const, label: 'Frozen · 60d+', max: Infinity },
]

function bandFor(days: number | null): (typeof BANDS)[number]['id'] {
    if (days == null) {
        return 'frozen'
    }
    for (const b of BANDS) {
        if (days <= b.max) {
            return b.id
        }
    }
    return 'frozen'
}

function buildRows(
    fleet: FleetRow[],
    activity: Record<string, AccountActivity>,
    projection: Record<string, ProjectionRow>
): EngagementRow[] {
    return fleet.map((account) => {
        const e = engagement(activity[account.externalId])
        return {
            account,
            daysSinceLastTouch: e.daysSinceLastTouch,
            lastNoteDate: e.lastNoteDate,
            lastTaskDate: e.lastTaskDate,
            arr: projection[account.externalId]?.arrDiscounted ?? null,
        }
    })
}

function EngagementBand({ label, rows }: { label: string; rows: EngagementRow[] }): JSX.Element | null {
    if (rows.length === 0) {
        return null
    }
    return (
        <section>
            <h3 className="text-base font-medium mb-2">
                {label} · {rows.length}
            </h3>
            <LemonTable<EngagementRow>
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
                        title: 'Days since last touch',
                        key: 'days',
                        align: 'right',
                        render: (_, r) => (r.daysSinceLastTouch == null ? '—' : `${r.daysSinceLastTouch}d`),
                        sorter: (a, b) =>
                            (a.daysSinceLastTouch ?? Number.MAX_SAFE_INTEGER) -
                            (b.daysSinceLastTouch ?? Number.MAX_SAFE_INTEGER),
                    },
                    {
                        title: 'Last note',
                        key: 'note',
                        render: (_, r) => r.lastNoteDate?.slice(0, 10) ?? '—',
                    },
                    {
                        title: 'Last task',
                        key: 'task',
                        render: (_, r) => r.lastTaskDate?.slice(0, 10) ?? '—',
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

export function EngagementTab(): JSX.Element {
    const { fleet, projection, activity, activityLoading } = useValues(csmHudSceneLogic)
    const rows = buildRows(fleet, activity, projection)
    const byBand: Record<(typeof BANDS)[number]['id'], EngagementRow[]> = {
        fresh: [],
        cooling: [],
        cold: [],
        frozen: [],
    }
    for (const r of rows) {
        byBand[bandFor(r.daysSinceLastTouch)].push(r)
    }

    const totalTracked = rows.filter((r) => r.daysSinceLastTouch != null).length
    return (
        <div className="space-y-4">
            <div className="text-muted text-sm">
                {totalTracked} tracked · {byBand.frozen.length} frozen · {fleet.length - totalTracked} never touched
            </div>
            {fleet.length === 0 ? (
                <div className="text-muted py-8 text-center">
                    Engagement requires fleet rows. Load is empty on this team.
                </div>
            ) : activityLoading && Object.keys(activity).length === 0 ? (
                <div className="text-muted py-8 text-center">Loading recent notes &amp; tasks…</div>
            ) : (
                BANDS.map((b) => <EngagementBand key={b.id} label={b.label} rows={byBand[b.id]} />)
            )}
        </div>
    )
}
