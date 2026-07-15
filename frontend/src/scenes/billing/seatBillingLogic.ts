import { actions, afterMount, connect, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api, { ApiError } from 'lib/api'
import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { membersLogic } from 'scenes/organization/membersLogic'
import { organizationLogic } from 'scenes/organizationLogic'

import { CODE_FREE_PLAN_PREFIX, CODE_PLAN_ALPHA_PRO, CODE_PRO_PLAN_PREFIX, CODE_PRODUCT_KEY } from './constants'
import type { seatBillingLogicType } from './seatBillingLogicType'
import type { SeatData } from './types'

export function isProPlanKey(planKey: string | null | undefined): boolean {
    return !!planKey && planKey.startsWith(CODE_PRO_PLAN_PREFIX)
}

export function isFreePlanKey(planKey: string | null | undefined): boolean {
    return !!planKey && planKey.startsWith(CODE_FREE_PLAN_PREFIX)
}

export function isAlphaPlanKey(planKey: string | null | undefined): boolean {
    return planKey === CODE_PLAN_ALPHA_PRO
}

export function canCancelSeat(seat: Pick<SeatData, 'status'>, isAdmin: boolean): boolean {
    return isAdmin && seat.status === 'active'
}

// TODO: Replace with `seat.price` once billing exposes it via SeatSerializer
export function seatPriceFromPlanKey(planKey: string): number {
    if (isFreePlanKey(planKey)) {
        return 0
    }
    const match = planKey.match(/posthog-code-pro-(\d+)/)
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
            membersLogic,
            ['members'],
            featureFlagLogic,
            ['featureFlags'],
        ],
        actions: [membersLogic, ['ensureAllMembersLoaded']],
    })),
    actions({
        adminCancelSeat: (userDistinctId: string) => ({ userDistinctId }),
    }),
    loaders(() => ({
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
    listeners(({ actions }) => ({
        adminCancelSeat: async ({ userDistinctId }) => {
            try {
                await api.delete(`api/seats/${userDistinctId}/?product_key=${CODE_PRODUCT_KEY}`)
                lemonToast.success('Seat canceled')
                actions.loadOrgSeats()
            } catch (e) {
                lemonToast.error(seatErrorMessage(e, 'Failed to cancel seat'))
            }
        },
    })),
    afterMount(({ actions, values }) => {
        if (!values.featureFlags[FEATURE_FLAGS.POSTHOG_CODE_BILLING]) {
            return
        }
        actions.ensureAllMembersLoaded()
        if (values.isAdmin) {
            actions.loadOrgSeats()
        }
    }),
])
