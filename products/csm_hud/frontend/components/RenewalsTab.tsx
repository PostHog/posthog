import { useActions, useValues } from 'kea'

import { LemonSegmentedButton, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { csmHudSceneLogic, FleetRow } from '../logics/csmHudSceneLogic'
import { formatMoneyCompact } from '../utils/format'
import { healthBand } from '../utils/health'
import { ProjectionRow, renewal } from '../utils/projection'

interface RenewalRow {
    account: FleetRow
    projection: ProjectionRow
    days: number
    plan: 'Annual' | 'Monthly'
    contractEnd: string | null
    arr: number | null
}

const BANDS = [
    { id: 'burning' as const, label: 'Burning · ≤30d', max: 30 },
    { id: 'warn' as const, label: 'Warn · 31–60d', max: 60 },
    { id: 'watch' as const, label: 'Watch · 61–90d', max: 90 },
    { id: 'future' as const, label: 'Future · 91d+', max: Infinity },
]

function bandFor(days: number): (typeof BANDS)[number]['id'] {
    for (const b of BANDS) {
        if (days <= b.max) {
            return b.id
        }
    }
    return 'future'
}

function buildRows(fleet: FleetRow[], projection: Record<string, ProjectionRow>): RenewalRow[] {
    const out: RenewalRow[] = []
    for (const account of fleet) {
        const p = projection[account.externalId]
        if (!p) {
            continue
        }
        const r = renewal(p)
        if (!r) {
            continue
        }
        // Prefer contract end (Salesforce, authoritative for renewals);
        // fall back to billing period end for monthly plans without a contract.
        let days: number | null = null
        let contractEnd: string | null = null
        if (r.daysUntilContractEnd != null && r.daysUntilContractEnd >= 0) {
            days = r.daysUntilContractEnd
            contractEnd = r.contractEnd
        } else if (r.daysUntilRenewal != null && r.daysUntilRenewal >= 0) {
            days = r.daysUntilRenewal
            contractEnd = r.billingPeriodEnd
        }
        if (days == null) {
            continue
        }
        const plan: 'Annual' | 'Monthly' = (r.termMonths ?? 0) >= 12 ? 'Annual' : 'Monthly'
        out.push({
            account,
            projection: p,
            days,
            plan,
            contractEnd,
            arr: r.arrDiscounted,
        })
    }
    return out
}

function RenewalsBand({ label, rows }: { label: string; rows: RenewalRow[] }): JSX.Element | null {
    if (rows.length === 0) {
        return null
    }
    return (
        <section>
            <h3 className="text-base font-medium mb-2">
                {label} · {rows.length}
            </h3>
            <LemonTable<RenewalRow>
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
                        title: 'Plan',
                        key: 'plan',
                        render: (_, r) => (
                            <LemonTag type={r.plan === 'Annual' ? 'success' : 'warning'}>{r.plan}</LemonTag>
                        ),
                        sorter: (a, b) => a.plan.localeCompare(b.plan),
                    },
                    {
                        title: 'Days until',
                        key: 'days',
                        align: 'right',
                        render: (_, r) => `${r.days}d`,
                        sorter: (a, b) => a.days - b.days,
                    },
                    {
                        title: 'Renews',
                        key: 'date',
                        render: (_, r) => r.contractEnd?.slice(0, 10) ?? '—',
                    },
                    {
                        title: 'Health',
                        key: 'health',
                        align: 'right',
                        render: (_, r) => {
                            const band = healthBand(r.account.healthScore)
                            return (
                                <span
                                    className={
                                        band === 'bad' ? 'text-danger' : band === 'ok' ? 'text-warning' : 'text-success'
                                    }
                                >
                                    {r.account.healthScore != null ? r.account.healthScore.toFixed(1) : '—'}
                                </span>
                            )
                        },
                        sorter: (a, b) => (a.account.healthScore ?? -1) - (b.account.healthScore ?? -1),
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

export function RenewalsTab(): JSX.Element {
    const { fleet, projection, projectionLoading, renewalsPlanFilter } = useValues(csmHudSceneLogic)
    const { setRenewalsPlanFilter } = useActions(csmHudSceneLogic)

    const allRows = buildRows(fleet, projection)
    const filteredRows = renewalsPlanFilter === 'annual' ? allRows.filter((r) => r.plan === 'Annual') : allRows

    const byBand: Record<(typeof BANDS)[number]['id'], RenewalRow[]> = {
        burning: [],
        warn: [],
        watch: [],
        future: [],
    }
    for (const r of filteredRows) {
        byBand[bandFor(r.days)].push(r)
    }

    return (
        <div className="space-y-4">
            <div className="flex items-center justify-between gap-2">
                <div className="text-muted text-sm">
                    {filteredRows.length} renewals · {byBand.burning.length} burning · {byBand.warn.length} warn
                </div>
                <LemonSegmentedButton
                    value={renewalsPlanFilter}
                    onChange={(v) => setRenewalsPlanFilter(v)}
                    options={[
                        { value: 'annual', label: 'Annual only' },
                        { value: 'all', label: 'All' },
                    ]}
                    size="small"
                />
            </div>
            {filteredRows.length === 0 ? (
                <div className="text-muted py-8 text-center">
                    {projectionLoading ? 'Loading projection…' : 'No upcoming renewals match the current filter.'}
                </div>
            ) : (
                BANDS.map((b) => <RenewalsBand key={b.id} label={b.label} rows={byBand[b.id]} />)
            )}
        </div>
    )
}
