import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonDialog, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { billingLogic } from './billingLogic'
import { CODE_PLAN_PRO } from './constants'
import {
    canReactivateSeat,
    isAlphaPlanKey,
    isProPlanKey,
    seatBillingLogic,
    seatPriceFromPlanKey,
} from './seatBillingLogic'
import type { SeatData, SeatStatus } from './types'

const ALPHA_PLAN_MIGRATION_DATE = 'June 4, 2026'

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
    const {
        displaySeats,
        orgSeatsLoading,
        isAdmin,
        members,
        activeCount,
        cancelingCount,
        monthlyTotal,
        hasAlphaSeats,
    } = useValues(seatBillingLogic)
    const { adminCancelSeat, adminUpgradeSeat, adminReactivateSeat } = useActions(seatBillingLogic)
    const { billing } = useValues(billingLogic)

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
            {hasAlphaSeats && (
                <LemonBanner type="info" className="mb-4">
                    Alpha plan seats will be moved to the free plan automatically on {ALPHA_PLAN_MIGRATION_DATE}. After
                    that, you'll be able to upgrade them to the Pro plan.
                </LemonBanner>
            )}
            <LemonTable
                loading={orgSeatsLoading}
                dataSource={displaySeats}
                defaultSorting={{ columnKey: 'user', order: 1 }}
                emptyState="No Code seats have been provisioned yet"
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
                            if (isAlphaPlanKey(seat.plan_key)) {
                                return (
                                    <Tooltip
                                        title={`Alpha seats will be migrated to the free plan on ${ALPHA_PLAN_MIGRATION_DATE}.`}
                                    >
                                        <LemonTag type="completion">{planLabel(seat.plan_key)}</LemonTag>
                                    </Tooltip>
                                )
                            }
                            return (
                                <LemonTag type={isProPlanKey(seat.plan_key) ? 'primary' : 'muted'}>
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
                            if (!billing?.has_active_subscription || !isAdmin) {
                                return null
                            }
                            const canUpgrade =
                                seat.status === 'active' &&
                                !isProPlanKey(seat.plan_key) &&
                                !isAlphaPlanKey(seat.plan_key)
                            const canCancel = seat.status === 'active'
                            const canReactivate = canReactivateSeat(seat)

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
                                                    onClick={() => {
                                                        LemonDialog.open({
                                                            title: 'Upgrade this seat to Pro?',
                                                            description:
                                                                'A prorated charge will be applied for the remainder of the billing period. This cannot be reverted without canceling.',
                                                            primaryButton: {
                                                                children: 'Upgrade to Pro',
                                                                onClick: () =>
                                                                    adminUpgradeSeat(
                                                                        seat.user_distinct_id,
                                                                        CODE_PLAN_PRO
                                                                    ),
                                                            },
                                                            secondaryButton: { children: 'Cancel' },
                                                        })
                                                    }}
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
