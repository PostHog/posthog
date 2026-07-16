import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonDialog, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { canCancelSeat, isAlphaPlanKey, isProPlanKey, seatBillingLogic, seatPriceFromPlanKey } from './seatBillingLogic'
import type { SeatData, SeatStatus } from './types'

function planLabel(planKey: string): string {
    if (isAlphaPlanKey(planKey)) {
        return 'Alpha'
    }
    if (isProPlanKey(planKey)) {
        return 'Pro'
    }
    return 'Free'
}

function formatSeatDate(value: string | number | null): string {
    if (!value) {
        return '–'
    }
    const parsed = typeof value === 'number' ? dayjs.unix(value) : dayjs(value)
    if (!parsed.isValid() || parsed.year() <= 1970) {
        return '–'
    }
    return parsed.format('MMM D, YYYY')
}

function statusColor(status: SeatStatus): 'success' | 'warning' | 'muted' | 'primary' {
    switch (status) {
        case 'active':
            return 'success'
        case 'canceling':
            return 'warning'
        case 'expired':
        case 'withdrawn':
            return 'muted'
        default:
            return 'primary'
    }
}

export function CodeSeatsSection(): JSX.Element {
    const { displaySeats, orgSeatsLoading, isAdmin, members, activeCount, cancelingCount, monthlyTotal } =
        useValues(seatBillingLogic)
    const { adminCancelSeat } = useActions(seatBillingLogic)

    function getUserInfo(seat: SeatData): { name: string; email: string } | null {
        if (!members) {
            return null
        }
        const member = members.find((m) => m.user.distinct_id === seat.user_distinct_id)
        if (!member) {
            return null
        }
        return { name: member.user.first_name, email: member.user.email }
    }

    return (
        <div>
            <div className="flex items-center justify-between mb-4">
                <div>
                    <h3 className="mb-1 text-lg font-semibold">Code seats</h3>
                    {isAdmin && (
                        <span className="text-muted text-sm">
                            {activeCount} active{cancelingCount > 0 ? `, ${cancelingCount} canceling` : ''} &middot;{' '}
                            <Tooltip title="Reflects the monthly rate, not prorated charges">
                                ${monthlyTotal}/mo
                            </Tooltip>
                        </span>
                    )}
                </div>
            </div>
            <LemonBanner type="info" className="mb-4">
                PostHog Code with usage-based billing is launching shortly. New seats, upgrades, and reactivations are
                no longer available. You can still cancel active seats below.
            </LemonBanner>
            <LemonTable
                loading={orgSeatsLoading}
                dataSource={displaySeats}
                defaultSorting={{ columnKey: 'user', order: 1 }}
                emptyState="No Code seats"
                columns={[
                    {
                        title: 'User',
                        key: 'user',
                        sorter: (a, b) => {
                            const aName = getUserInfo(a)?.name ?? a.user_distinct_id
                            const bName = getUserInfo(b)?.name ?? b.user_distinct_id
                            return aName.localeCompare(bName)
                        },
                        render: (_, seat: SeatData) => {
                            const info = getUserInfo(seat)
                            if (info) {
                                return (
                                    <div>
                                        <div className="font-semibold">{info.name}</div>
                                        <div className="text-muted text-xs">{info.email}</div>
                                    </div>
                                )
                            }
                            return <span className="text-muted">{seat.user_distinct_id.slice(0, 8)}...</span>
                        },
                    },
                    {
                        title: 'Plan',
                        key: 'plan',
                        align: 'center',
                        render: (_, seat: SeatData) => {
                            return (
                                <LemonTag
                                    type={
                                        isAlphaPlanKey(seat.plan_key)
                                            ? 'completion'
                                            : isProPlanKey(seat.plan_key)
                                              ? 'primary'
                                              : 'muted'
                                    }
                                >
                                    {planLabel(seat.plan_key)}
                                </LemonTag>
                            )
                        },
                    },
                    {
                        title: 'Status',
                        key: 'status',
                        align: 'center',
                        render: (_, seat: SeatData) => (
                            <LemonTag type={statusColor(seat.status)}>{seat.status}</LemonTag>
                        ),
                    },
                    {
                        title: 'Cost',
                        key: 'cost',
                        render: (_, seat: SeatData) => {
                            const price = seatPriceFromPlanKey(seat.plan_key)
                            return price > 0 ? `$${price}/mo` : 'Free'
                        },
                    },
                    {
                        title: 'Started',
                        key: 'active_from',
                        render: (_, seat: SeatData) => formatSeatDate(seat.active_from),
                    },
                    {
                        title: 'Expires',
                        key: 'active_until',
                        render: (_, seat: SeatData) => formatSeatDate(seat.active_until),
                    },
                    {
                        title: '',
                        key: 'actions',
                        width: 0,
                        render: (_, seat: SeatData) => {
                            if (!canCancelSeat(seat, isAdmin)) {
                                return null
                            }

                            return (
                                <More
                                    overlay={
                                        <LemonButton
                                            fullWidth
                                            onClick={() => {
                                                LemonDialog.open({
                                                    title: 'Cancel this seat?',
                                                    description:
                                                        'The seat will remain active until the end of the current billing period.',
                                                    primaryButton: {
                                                        children: 'Cancel seat',
                                                        status: 'danger',
                                                        onClick: () => adminCancelSeat(seat.user_distinct_id),
                                                    },
                                                    secondaryButton: { children: 'Keep seat' },
                                                })
                                            }}
                                        >
                                            Cancel seat
                                        </LemonButton>
                                    }
                                />
                            )
                        },
                    },
                ]}
            />
        </div>
    )
}
