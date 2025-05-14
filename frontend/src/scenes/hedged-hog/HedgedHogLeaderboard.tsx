import { IconCrown, IconStar } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { useEffect } from 'react'

import { hedgedHogLogic, LeaderboardType } from './hedgedHogLogic'

export const LeaderboardContent = (): JSX.Element => {
    const { leaderboard, leaderboardLoading, currentLeaderboardType } = useValues(hedgedHogLogic)
    const { loadLeaderboard } = useActions(hedgedHogLogic)

    useEffect(() => {
        loadLeaderboard(currentLeaderboardType)
    }, [currentLeaderboardType])

    const leaderboardOptions = [
        { label: 'Balance', value: 'balance' },
        { label: 'Win Rate', value: 'win_rate' },
        { label: 'Trading Volume', value: 'volume' },
    ]

    const getRankIcon = (index: number): JSX.Element | null => {
        if (index === 0) {
            return <IconStar className="text-xl text-warning" />
        }
        if (index === 1) {
            return <IconStar className="text-xl text-primary" />
        }
        if (index === 2) {
            return <IconStar className="text-xl text-danger" />
        }
        return null
    }

    return (
        <div className="mt-4">
            <div className="flex items-center justify-between mb-4">
                <h3 className="m-0">Leaderboard</h3>
                <LemonSelect
                    value={currentLeaderboardType}
                    onChange={(value) => loadLeaderboard(value as LeaderboardType)}
                    options={leaderboardOptions}
                    size="small"
                />
            </div>

            {leaderboardLoading ? (
                <LemonSkeleton className="h-60" />
            ) : leaderboard.length === 0 ? (
                <LemonCard className="p-6">
                    <div className="text-center">
                        <IconCrown className="text-4xl mb-4 text-warning" />
                        <h3 className="text-lg font-semibold">No Data Yet</h3>
                        <p className="text-muted mt-2">There are no users with data for this leaderboard type yet.</p>
                        <LemonButton
                            type="primary"
                            className="mt-4"
                            onClick={() => loadLeaderboard(currentLeaderboardType)}
                        >
                            Refresh Leaderboard
                        </LemonButton>
                    </div>
                </LemonCard>
            ) : (
                <LemonCard>
                    <LemonTable
                        dataSource={leaderboard}
                        columns={[
                            {
                                title: 'Rank',
                                render: function RenderRank(_, __, index) {
                                    return (
                                        <div className="flex items-center">
                                            {getRankIcon(index) || <span>{index + 1}</span>}
                                        </div>
                                    )
                                },
                                width: 60,
                            },
                            {
                                title: 'User',
                                dataIndex: 'user_email',
                                render: function RenderUser(email) {
                                    return <span className="font-semibold">{email}</span>
                                },
                            },
                            ...(currentLeaderboardType === 'balance'
                                ? [
                                      {
                                          title: 'Balance',
                                          dataIndex: 'balance',
                                          render: function RenderBalance(balance) {
                                              return (
                                                  <span className="font-semibold text-success">
                                                      {parseFloat(balance?.toString() || '0').toLocaleString()}{' '}
                                                      Hogecoins
                                                  </span>
                                              )
                                          },
                                      },
                                  ]
                                : []),
                            ...(currentLeaderboardType === 'win_rate'
                                ? [
                                      {
                                          title: 'Win Rate',
                                          dataIndex: 'win_rate',
                                          render: function RenderWinRate(winRate) {
                                              return (
                                                  <span className="font-semibold">
                                                      {parseFloat(winRate?.toString() || '0').toFixed(1)}%
                                                  </span>
                                              )
                                          },
                                      },
                                      {
                                          title: 'Wins / Total',
                                          render: function RenderWinTotal(_, record) {
                                              return (
                                                  <span>
                                                      {record.total_wins} / {record.total_bets}
                                                  </span>
                                              )
                                          },
                                      },
                                  ]
                                : []),
                            ...(currentLeaderboardType === 'volume'
                                ? [
                                      {
                                          title: 'Trading Volume',
                                          dataIndex: 'total_volume',
                                          render: function RenderVolume(volume) {
                                              return (
                                                  <span className="font-semibold">
                                                      {parseFloat(volume?.toString() || '0').toLocaleString()} Hogecoins
                                                  </span>
                                              )
                                          },
                                      },
                                  ]
                                : []),
                        ]}
                        rowKey="user_email"
                    />
                </LemonCard>
            )}
        </div>
    )
}
