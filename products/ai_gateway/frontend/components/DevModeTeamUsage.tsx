import { useActions, useValues } from 'kea'

import { LemonBanner, LemonInput, LemonSelect, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { DevTokenActivityApi, DevUserUsageApi } from '../generated/api.schemas'
import { PAGE_SIZE_OPTIONS, devModeTeamUsageLogic } from '../logics/devModeTeamUsageLogic'

// Four places, because single calls cost fractions of a cent.
function usd(value: string): JSX.Element {
    return <span translate="no">${Number(value).toFixed(4)}</span>
}

const ACTIVITY_TAG: Record<string, { label: string; type: 'success' | 'danger' | 'default' }> = {
    minted: { label: 'Minted', type: 'success' },
    revoked: { label: 'Revoked', type: 'danger' },
}

export function DevModeTeamUsage(): JSX.Element {
    const { teamUsageLoading, teamUsage, refusal, isPayingTeam, search, pageSize, filteredUsers, filteredActivity } =
        useValues(devModeTeamUsageLogic)
    const { setSearch, setPageSize } = useActions(devModeTeamUsageLogic)

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
            <div className="flex flex-wrap items-center justify-between gap-2">
                <LemonInput type="search" placeholder="Search by email" value={search} onChange={setSearch} />
                <LemonSelect
                    value={pageSize}
                    onChange={(value) => setPageSize(value)}
                    options={PAGE_SIZE_OPTIONS.map((size) => ({ value: size, label: `Show ${size}` }))}
                    size="small"
                />
            </div>
            <LemonTable<DevUserUsageApi>
                dataSource={filteredUsers}
                loading={teamUsageLoading}
                pagination={{ pageSize }}
                emptyState={
                    search ? 'No users match this search' : 'No developer mode tokens or spend in the last 30 days'
                }
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
            <h3 className="mb-0">Activity</h3>
            <LemonTable<DevTokenActivityApi>
                dataSource={filteredActivity}
                loading={teamUsageLoading}
                pagination={{ pageSize }}
                emptyState={search ? 'No activity matches this search' : 'No mints or revokes in the last 30 days'}
                columns={[
                    {
                        title: 'When',
                        key: 'at',
                        render: (_, entry) => <TZLabel time={entry.at} />,
                    },
                    {
                        title: 'Action',
                        key: 'activity',
                        render: (_, entry) => {
                            const tag = ACTIVITY_TAG[entry.activity] ?? { label: entry.activity, type: 'default' }
                            return <LemonTag type={tag.type}>{tag.label}</LemonTag>
                        },
                    },
                    {
                        title: 'Token owner',
                        key: 'owner_email',
                        render: (_, entry) => entry.owner_email ?? <span className="text-secondary">Unknown</span>,
                    },
                    {
                        title: 'By',
                        key: 'actor_email',
                        render: (_, entry) =>
                            entry.actor_email && entry.actor_email !== entry.owner_email ? (
                                entry.actor_email
                            ) : (
                                <span className="text-secondary">Owner</span>
                            ),
                    },
                    {
                        title: 'Source',
                        key: 'client',
                        render: (_, entry) =>
                            entry.client ? <LemonTag>{entry.client === 'cli' ? 'CLI' : 'Web'}</LemonTag> : null,
                    },
                    {
                        title: 'Spend limit',
                        key: 'cap_usd',
                        render: (_, entry) => (entry.cap_usd ? <span translate="no">${entry.cap_usd}</span> : null),
                    },
                ]}
            />
        </div>
    )
}
