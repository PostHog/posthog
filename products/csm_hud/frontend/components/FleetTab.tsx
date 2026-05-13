import { useValues } from 'kea'

import { LemonTable, LemonTag } from '@posthog/lemon-ui'

import { csmHudSceneLogic, FleetRow } from '../logics/csmHudSceneLogic'
import { formatMoney } from '../utils/format'
import { healthBand, healthLabel } from '../utils/health'

const HEALTH_TAG_TYPE: Record<ReturnType<typeof healthBand>, 'success' | 'warning' | 'danger' | 'default'> = {
    good: 'success',
    ok: 'warning',
    bad: 'danger',
    unknown: 'default',
}

export function FleetTab(): JSX.Element {
    const { fleet, fleetLoading } = useValues(csmHudSceneLogic)

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
                    title: 'MRR',
                    key: 'mrr',
                    align: 'right',
                    render: (_, row) => formatMoney(row.mrr),
                    sorter: (a, b) => (a.mrr ?? 0) - (b.mrr ?? 0),
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
