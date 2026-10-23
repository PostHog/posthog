import { useValues } from 'kea'

import { LemonBanner, LemonTable } from '@posthog/lemon-ui'

import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { TZLabel } from 'lib/components/TZLabel'

import { ActivityScope } from '~/types'

import type { DevUserUsageApi } from '../generated/api.schemas'
import { devModeTeamUsageLogic } from '../logics/devModeTeamUsageLogic'

// Four places, because single calls cost fractions of a cent.
function usd(value: string): JSX.Element {
    return <span translate="no">${Number(value).toFixed(4)}</span>
}

export function DevModeTeamUsage(): JSX.Element {
    const { teamUsage, teamUsageLoading, refusal, isPayingTeam } = useValues(devModeTeamUsageLogic)

    if (refusal && !teamUsage) {
        return <LemonBanner type="warning">{refusal}</LemonBanner>
    }
    if (teamUsage && !isPayingTeam) {
        return (
            <LemonBanner type="info">
                Developer mode is billed to project {teamUsage.paying_team_id}. Switch to that project to see team usage
                and activity.
            </LemonBanner>
        )
    }

    return (
        <div className="flex flex-col gap-4">
            <p className="mb-0">
                Spend is settled gateway cost for calls made with developer mode tokens. Reserved is the sum of token
                caps minted in the last 24 hours, which counts against each user's daily limit.
            </p>
            <LemonTable<DevUserUsageApi>
                dataSource={teamUsage?.users ?? []}
                loading={teamUsageLoading}
                emptyState="No developer mode tokens or spend in the last 30 days"
                rowKey="distinct_id"
                columns={[
                    {
                        title: 'User',
                        key: 'email',
                        render: (_, row) =>
                            row.email ?? (
                                <span className="text-secondary" translate="no">
                                    Unknown user ({row.distinct_id})
                                </span>
                            ),
                    },
                    {
                        title: 'Spend 24h',
                        key: 'spend_usd_24h',
                        render: (_, row) => usd(row.spend_usd_24h),
                        sorter: (a, b) => Number(a.spend_usd_24h) - Number(b.spend_usd_24h),
                    },
                    {
                        title: 'Spend 7d',
                        key: 'spend_usd_7d',
                        render: (_, row) => usd(row.spend_usd_7d),
                        sorter: (a, b) => Number(a.spend_usd_7d) - Number(b.spend_usd_7d),
                    },
                    {
                        title: 'Spend 30d',
                        key: 'spend_usd_30d',
                        render: (_, row) => usd(row.spend_usd_30d),
                        sorter: (a, b) => Number(a.spend_usd_30d) - Number(b.spend_usd_30d),
                    },
                    {
                        title: 'Reserved 24h',
                        key: 'reserved_usd_24h',
                        render: (_, row) => usd(row.reserved_usd_24h),
                    },
                    {
                        title: 'Tokens 24h / 30d',
                        key: 'tokens_minted_30d',
                        render: (_, row) => (
                            <span translate="no">
                                {row.tokens_minted_24h} / {row.tokens_minted_30d}
                            </span>
                        ),
                        sorter: (a, b) => a.tokens_minted_30d - b.tokens_minted_30d,
                    },
                    { title: 'Live', key: 'live_tokens', dataIndex: 'live_tokens' },
                    { title: 'Revoked 30d', key: 'revoked_30d', dataIndex: 'revoked_30d' },
                    {
                        title: 'Last minted',
                        key: 'last_minted_at',
                        render: (_, row) => (row.last_minted_at ? <TZLabel time={row.last_minted_at} /> : null),
                    },
                ]}
            />
            {isPayingTeam ? <ActivityLog scope={ActivityScope.DEV_GATEWAY_TOKEN} /> : null}
        </div>
    )
}
