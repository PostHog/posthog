import { useValues } from 'kea'

import { LemonTable, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { csmHudSceneLogic, FleetRow } from '../logics/csmHudSceneLogic'
import { formatMoney, formatMoneyCompact } from '../utils/format'
import { healthBand, healthLabel } from '../utils/health'
import { deriveProjection, ProjectionRow } from '../utils/projection'

const HEALTH_TAG_TYPE: Record<ReturnType<typeof healthBand>, 'success' | 'warning' | 'danger' | 'default'> = {
    good: 'success',
    ok: 'warning',
    bad: 'danger',
    unknown: 'default',
}

function formulaTooltip(p: ProjectionRow): string {
    const derived = deriveProjection(p)
    return [
        `m1 ${formatMoney(p.priorMonthMrr)} × 0.5 + m2 ${formatMoney(p.m2Actual)} × 0.3 + m3 ${formatMoney(p.m3Actual)} × 0.2`,
        `= weighted ${formatMoney(p.weightedBaseline)} (renormalized over ${p.historyMonths}/3 mo)`,
        `daily_rate ${formatMoney(derived.dailyRate)}/d (weighted / ${derived.daysInCurrentMonth})`,
        `MTD ${formatMoney(p.currentMonthSpend)} + (${formatMoney(derived.dailyRate)}/d × ${derived.daysRemaining}d) = ${formatMoney(p.forecastedMrr)}`,
    ].join('\n')
}

function MomCell({ projection }: { projection: ProjectionRow | undefined }): JSX.Element {
    if (!projection) {
        return <span className="text-muted">—</span>
    }
    const derived = deriveProjection(projection)
    if (derived.momGrowthPct == null) {
        return <span className="text-muted">—</span>
    }
    const sign = derived.momGrowthPct >= 0 ? '+' : ''
    const tone = derived.momGrowthPct >= 0 ? 'text-success' : 'text-danger'
    return <span className={tone}>{`${sign}${derived.momGrowthPct.toFixed(1)}%`}</span>
}

export function FleetTab(): JSX.Element {
    const { fleet, fleetLoading, projection, projectionLoading } = useValues(csmHudSceneLogic)

    return (
        <LemonTable<FleetRow>
            loading={fleetLoading}
            dataSource={fleet}
            rowKey="id"
            columns={[
                {
                    title: 'Account',
                    key: 'name',
                    render: (_, row) => <span className="font-medium">{row.name}</span>,
                    sorter: (a, b) => a.name.localeCompare(b.name),
                },
                {
                    title: 'Health',
                    key: 'health',
                    render: (_, row) => {
                        const band = healthBand(row.healthScore)
                        return (
                            <LemonTag type={HEALTH_TAG_TYPE[band]}>
                                {row.healthScore != null ? row.healthScore.toFixed(1) : '—'} ·{' '}
                                {healthLabel(row.healthScore)}
                            </LemonTag>
                        )
                    },
                    sorter: (a, b) => (a.healthScore ?? -1) - (b.healthScore ?? -1),
                },
                {
                    title: 'Last month',
                    key: 'lastMonth',
                    align: 'right',
                    render: (_, row) =>
                        projectionLoading && !projection[row.externalId] ? (
                            <span className="text-muted">…</span>
                        ) : (
                            formatMoneyCompact(projection[row.externalId]?.priorMonthMrr ?? null)
                        ),
                    sorter: (a, b) =>
                        (projection[a.externalId]?.priorMonthMrr ?? 0) - (projection[b.externalId]?.priorMonthMrr ?? 0),
                },
                {
                    title: 'This month (MTD)',
                    key: 'mtd',
                    align: 'right',
                    render: (_, row) =>
                        projectionLoading && !projection[row.externalId] ? (
                            <span className="text-muted">…</span>
                        ) : (
                            formatMoneyCompact(projection[row.externalId]?.currentMonthSpend ?? null)
                        ),
                    sorter: (a, b) =>
                        (projection[a.externalId]?.currentMonthSpend ?? 0) -
                        (projection[b.externalId]?.currentMonthSpend ?? 0),
                },
                {
                    title: 'Projected EoM',
                    key: 'projected',
                    align: 'right',
                    render: (_, row) => {
                        const p = projection[row.externalId]
                        if (!p && projectionLoading) {
                            return <span className="text-muted">…</span>
                        }
                        if (!p) {
                            return <span className="text-muted">—</span>
                        }
                        return (
                            <Tooltip title={<pre className="m-0 text-xs">{formulaTooltip(p)}</pre>}>
                                <span>{formatMoneyCompact(p.forecastedMrr)}</span>
                            </Tooltip>
                        )
                    },
                    sorter: (a, b) =>
                        (projection[a.externalId]?.forecastedMrr ?? 0) - (projection[b.externalId]?.forecastedMrr ?? 0),
                },
                {
                    title: 'MoM',
                    key: 'mom',
                    align: 'right',
                    render: (_, row) => <MomCell projection={projection[row.externalId]} />,
                },
                {
                    title: 'ARR (contract)',
                    key: 'arr',
                    align: 'right',
                    render: (_, row) => formatMoneyCompact(projection[row.externalId]?.arrDiscounted ?? null),
                    sorter: (a, b) =>
                        (projection[a.externalId]?.arrDiscounted ?? 0) - (projection[b.externalId]?.arrDiscounted ?? 0),
                },
                {
                    title: 'Users',
                    key: 'users',
                    align: 'right',
                    render: (_, row) => row.usersCount.toLocaleString(),
                    sorter: (a, b) => a.usersCount - b.usersCount,
                },
            ]}
            emptyState={
                <div className="text-center py-8 text-muted">
                    No accounts found for your CSM email. Either vitally_accounts isn't synced for this team, or no
                    accounts have you set as CSM.
                </div>
            }
        />
    )
}
