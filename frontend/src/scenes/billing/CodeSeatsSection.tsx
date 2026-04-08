import { useActions, useValues } from 'kea'

import { LemonButton, LemonDialog, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { More } from 'lib/lemon-ui/LemonButton/More'

import { billingLogic } from './billingLogic'
import { CODE_PLAN_PRO } from './constants'
import { isProPlanKey, seatBillingLogic, seatPriceFromPlanKey } from './seatBillingLogic'
import type { SeatData } from './types'

function planLabel(planKey: string): string {
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

function statusColor(status: string): 'success' | 'warning' | 'muted' | 'primary' {
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

const STATUS_PRIORITY: Record<string, number> = {
    active: 0,
    canceling: 1,
    pending_payment: 2,
    pending: 3,
    expired: 4,
    withdrawn: 5,
}

export function CodeSeatsSection(): JSX.Element {
    const { orgSeats, orgSeatsLoading, isAdmin, members } = useValues(seatBillingLogic)
    const { adminCancelSeat, adminUpgradeSeat, adminReactivateSeat } = useActions(seatBillingLogic)
    const { billing } = useValues(billingLogic)

    const displaySeats = Object.values(
        orgSeats.reduce<Record<string, SeatData>>((acc, seat) => {
            const existing = acc[seat.user_distinct_id]
            if (!existing || (STATUS_PRIORITY[seat.status] ?? 99) < (STATUS_PRIORITY[existing.status] ?? 99)) {
                acc[seat.user_distinct_id] = seat
            }
            return acc
        }, {})
    )

    const activeCount = displaySeats.filter((s) => s.status === 'active').length
    const cancelingCount = displaySeats.filter((s) => s.status === 'canceling').length
    const monthlyTotal = displaySeats
        .filter((s) => s.status === 'active')
        .reduce((sum, s) => sum + seatPriceFromPlanKey(s.plan_key), 0)

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
                    <span className="text-muted text-sm">
                        {activeCount} active{cancelingCount > 0 ? `, ${cancelingCount} canceling` : ''} &middot; $
                        {monthlyTotal}/mo
                    </span>
                </div>
            </div>
            <LemonTable
                loading={orgSeatsLoading}
                dataSource={displaySeats}
                columns={[
                    {
                        title: 'User',
                        key: 'user',
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
                        render: (_, seat: SeatData) => (
                            <LemonTag type={isProPlanKey(seat.plan_key) ? 'primary' : 'muted'}>
                                {planLabel(seat.plan_key)}
                            </LemonTag>
                        ),
                    },
                    {
                        title: 'Status',
                        key: 'status',
                        render: (_, seat: SeatData) => (
                            <LemonTag type={statusColor(seat.status)}>{seat.status}</LemonTag>
                        ),
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
                            if (!billing?.has_active_subscription || !isAdmin) {
                                return null
                            }
                            const canUpgrade = seat.status === 'active' && !isProPlanKey(seat.plan_key)
                            const canCancel = seat.status === 'active'
                            const canReactivate = seat.status === 'canceling'

                            if (!canUpgrade && !canCancel && !canReactivate) {
                                return null
                            }

                            return (
                                <More
                                    overlay={
                                        <>
                                            {canUpgrade && (
                                                <LemonButton
                                                    fullWidth
                                                    onClick={() =>
                                                        adminUpgradeSeat(seat.user_distinct_id, CODE_PLAN_PRO)
                                                    }
                                                >
                                                    Upgrade to Pro
                                                </LemonButton>
                                            )}
                                            {canReactivate && (
                                                <LemonButton
                                                    fullWidth
                                                    onClick={() => adminReactivateSeat(seat.user_distinct_id)}
                                                >
                                                    Reactivate
                                                </LemonButton>
                                            )}
                                            {canCancel && (
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
                                            )}
                                        </>
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
