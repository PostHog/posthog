import { actions, afterMount, connect, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api, { ApiError } from 'lib/api'
import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { membersLogic } from 'scenes/organization/membersLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { CODE_FREE_PLAN_PREFIX, CODE_PRO_PLAN_PREFIX, CODE_PRODUCT_KEY } from './constants'
import type { seatBillingLogicType } from './seatBillingLogicType'
import type { SeatData } from './types'

export function isProPlanKey(planKey: string | null | undefined): boolean {
    return !!planKey && planKey.startsWith(CODE_PRO_PLAN_PREFIX)
}

export function isFreePlanKey(planKey: string | null | undefined): boolean {
    return !!planKey && planKey.startsWith(CODE_FREE_PLAN_PREFIX)
}

// TODO: Replace with `seat.price` once billing exposes it via SeatSerializer
export function seatPriceFromPlanKey(planKey: string): number {
    if (isFreePlanKey(planKey)) {
        return 0
    }
    const match = planKey.match(/posthog-code-(\d+)/)
    return match ? parseInt(match[1], 10) : 0
}

function seatErrorMessage(e: unknown, fallback: string): string {
    if (e instanceof ApiError) {
        return e.detail || e.data?.detail || e.data?.error || fallback
    }
    return fallback
}

export const seatBillingLogic = kea<seatBillingLogicType>([
    path(['scenes', 'billing', 'seatBillingLogic']),
    connect(() => ({
        values: [
            organizationLogic,
            ['currentOrganization'],
            userLogic,
            ['user'],
            membersLogic,
            ['members'],
            featureFlagLogic,
            ['featureFlags'],
        ],
        actions: [membersLogic, ['ensureAllMembersLoaded']],
    })),
    actions({
        upgradeSeat: (planKey: string) => ({ planKey }),
        cancelSeat: true,
        reactivateSeat: true,
        createSeat: (planKey: string) => ({ planKey }),
        adminCancelSeat: (userDistinctId: string) => ({ userDistinctId }),
        adminUpgradeSeat: (userDistinctId: string, planKey: string) => ({ userDistinctId, planKey }),
        adminReactivateSeat: (userDistinctId: string) => ({ userDistinctId }),
    }),
    loaders(() => ({
        mySeat: [
            null as SeatData | null,
            {
                loadMySeat: async (): Promise<SeatData | null> => {
                    try {
                        return await api.get(`api/seats/me/?product_key=${CODE_PRODUCT_KEY}`)
                    } catch (e) {
                        if (e instanceof ApiError && e.status === 404) {
                            return null
                        }
                        throw e
                    }
                },
            },
        ],
        orgSeats: [
            [] as SeatData[],
            {
                loadOrgSeats: async (): Promise<SeatData[]> => {
                    try {
                        const response = await api.get(`api/seats/?product_key=${CODE_PRODUCT_KEY}`)
                        return Array.isArray(response) ? response : (response?.seats ?? [])
                    } catch (e) {
                        if (e instanceof ApiError && e.status === 403) {
                            return []
                        }
                        lemonToast.error(seatErrorMessage(e, 'Failed to load organization seats'))
                        return []
                    }
                },
            },
        ],
    })),
    selectors({
        isAdmin: [
            (s) => [s.currentOrganization],
            (currentOrganization): boolean =>
                !!(
                    currentOrganization?.membership_level &&
                    currentOrganization.membership_level >= OrganizationMembershipLevel.Admin
                ),
        ],
        isPro: [(s) => [s.mySeat], (mySeat): boolean => isProPlanKey(mySeat?.plan_key)],
        isFree: [(s) => [s.mySeat], (mySeat): boolean => isFreePlanKey(mySeat?.plan_key)],
        canUpgrade: [
            (s) => [s.mySeat],
            (mySeat): boolean => !!mySeat && mySeat.status === 'active' && isFreePlanKey(mySeat.plan_key),
        ],
        canCancel: [(s) => [s.mySeat], (mySeat): boolean => !!mySeat && mySeat.status === 'active'],
        canReactivate: [(s) => [s.mySeat], (mySeat): boolean => !!mySeat && mySeat.status === 'canceling'],
        displaySeats: [
            (s) => [s.orgSeats],
            (orgSeats): SeatData[] => {
                const STATUS_PRIORITY: Record<string, number> = {
                    active: 0,
                    canceling: 1,
                    pending_payment: 2,
                    pending: 3,
                    expired: 4,
                    withdrawn: 5,
                }
                return Object.values(
                    orgSeats.reduce<Record<string, SeatData>>((acc, seat) => {
                        const existing = acc[seat.user_distinct_id]
                        if (
                            !existing ||
                            (STATUS_PRIORITY[seat.status] ?? 99) < (STATUS_PRIORITY[existing.status] ?? 99)
                        ) {
                            acc[seat.user_distinct_id] = seat
                        }
                        return acc
                    }, {})
                )
            },
        ],
        activeCount: [
            (s) => [s.displaySeats],
            (displaySeats): number => displaySeats.filter((s: SeatData) => s.status === 'active').length,
        ],
        cancelingCount: [
            (s) => [s.displaySeats],
            (displaySeats): number => displaySeats.filter((s: SeatData) => s.status === 'canceling').length,
        ],
        monthlyTotal: [
            (s) => [s.displaySeats],
            (displaySeats): number =>
                displaySeats
                    .filter((s: SeatData) => s.status === 'active')
                    .reduce((sum: number, s: SeatData) => sum + seatPriceFromPlanKey(s.plan_key), 0),
        ],
    }),
    listeners(({ actions, values }) => ({
        upgradeSeat: async ({ planKey }) => {
            try {
                await api.update(`api/seats/me/`, { product_key: CODE_PRODUCT_KEY, plan_key: planKey })
                lemonToast.success('Seat upgraded successfully')
                actions.loadMySeat()
                if (values.isAdmin) {
                    actions.loadOrgSeats()
                }
            } catch (e) {
                lemonToast.error(seatErrorMessage(e, 'Failed to upgrade seat'))
            }
        },
        cancelSeat: async () => {
            try {
                await api.delete(`api/seats/me/?product_key=${CODE_PRODUCT_KEY}`)
                lemonToast.success('Seat canceled')
                actions.loadMySeat()
                if (values.isAdmin) {
                    actions.loadOrgSeats()
                }
            } catch (e) {
                lemonToast.error(seatErrorMessage(e, 'Failed to cancel seat'))
            }
        },
        reactivateSeat: async () => {
            try {
                await api.create(`api/seats/me/reactivate/`, { product_key: CODE_PRODUCT_KEY })
                lemonToast.success('Seat reactivated')
                actions.loadMySeat()
                if (values.isAdmin) {
                    actions.loadOrgSeats()
                }
            } catch (e) {
                lemonToast.error(seatErrorMessage(e, 'Failed to reactivate seat'))
            }
        },
        createSeat: async ({ planKey }) => {
            try {
                await api.create(`api/seats/`, {
                    product_key: CODE_PRODUCT_KEY,
                    plan_key: planKey,
                    user_distinct_id: values.user?.distinct_id,
                })
                lemonToast.success('Seat created')
                actions.loadMySeat()
                if (values.isAdmin) {
                    actions.loadOrgSeats()
                }
            } catch (e) {
                lemonToast.error(seatErrorMessage(e, 'Failed to create seat'))
            }
        },
        adminCancelSeat: async ({ userDistinctId }) => {
            try {
                await api.delete(`api/seats/${userDistinctId}/?product_key=${CODE_PRODUCT_KEY}`)
                lemonToast.success('Seat canceled')
                actions.loadOrgSeats()
                if (userDistinctId === values.user?.distinct_id) {
                    actions.loadMySeat()
                }
            } catch (e) {
                lemonToast.error(seatErrorMessage(e, 'Failed to cancel seat'))
            }
        },
        adminUpgradeSeat: async ({ userDistinctId, planKey }) => {
            try {
                await api.update(`api/seats/${userDistinctId}/`, {
                    product_key: CODE_PRODUCT_KEY,
                    plan_key: planKey,
                })
                lemonToast.success('Seat upgraded')
                actions.loadOrgSeats()
                if (userDistinctId === values.user?.distinct_id) {
                    actions.loadMySeat()
                }
            } catch (e) {
                lemonToast.error(seatErrorMessage(e, 'Failed to upgrade seat'))
            }
        },
        adminReactivateSeat: async ({ userDistinctId }) => {
            try {
                await api.create(`api/seats/${userDistinctId}/reactivate/`, {
                    product_key: CODE_PRODUCT_KEY,
                })
                lemonToast.success('Seat reactivated')
                actions.loadOrgSeats()
                if (userDistinctId === values.user?.distinct_id) {
                    actions.loadMySeat()
                }
            } catch (e) {
                lemonToast.error(seatErrorMessage(e, 'Failed to reactivate seat'))
            }
        },
    })),
    afterMount(({ actions, values }) => {
        if (!values.featureFlags[FEATURE_FLAGS.POSTHOG_CODE_BILLING]) {
            return
        }
        actions.loadMySeat()
        actions.ensureAllMembersLoaded()
        if (values.isAdmin) {
            actions.loadOrgSeats()
        }
    }),
])
