import { actions, afterMount, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { billingLogic } from 'scenes/billing/billingLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { ClaimedCouponInfo, CouponsOverview } from '~/types'

import type { couponLogicType } from './couponLogicType'

export interface CouponLogicProps {
    campaign?: string
}

export interface CouponFormValues {
    code: string
    organization_name: string
}

export const couponLogic = kea<couponLogicType>([
    path(['scenes', 'coupons', 'couponLogic']),
    props({} as CouponLogicProps),
    connect(() => ({
        values: [
            userLogic,
            ['user'],
            organizationLogic,
            ['currentOrganization', 'isAdminOrOwner'],
            billingLogic,
            ['billing', 'billingLoading'],
        ],
        actions: [billingLogic, ['loadBillingSuccess']],
    })),
    actions({
        setClaimed: (claimed: boolean) => ({ claimed }),
        setClaimedDetails: (details: any) => ({ details }),
    }),
    loaders(() => ({
        couponsOverview: [
            null as CouponsOverview | null,
            {
                loadCouponsOverview: async () => {
                    return await api.get('api/billing/coupons/overview')
                },
            },
        ],
    })),
    reducers({
        claimed: [false, { setClaimed: (_, { claimed }) => claimed }],
        claimedDetails: [null as any, { setClaimedDetails: (_, { details }) => details }],
    }),
    selectors({
        getClaimedCouponForCampaign: [
            (s) => [s.couponsOverview],
            (couponsOverview) =>
                (campaignSlug: string): ClaimedCouponInfo | null => {
                    return couponsOverview?.claimed_coupons?.find((c) => c.campaign_slug === campaignSlug) || null
                },
        ],
        activeCoupons: [
            (s) => [s.couponsOverview],
            (couponsOverview): ClaimedCouponInfo[] => {
                return couponsOverview?.claimed_coupons?.filter((c) => c.status === 'claimed') ?? []
            },
        ],
    }),
    forms(({ values, actions, props }) => ({
        coupon: {
            defaults: {
                code: '',
                organization_name: values.currentOrganization?.name || '',
            } as CouponFormValues,
            errors: ({ code }) => {
                if (!values.billingLoading && !values.billing?.has_active_subscription) {
                    return {
                        _form: 'You need to be on a paid plan before claiming this coupon',
                    }
                }
                return {
                    code: !code ? 'Please enter a coupon code' : undefined,
                }
            },
            submit: async (formValues: CouponFormValues) => {
                try {
                    const res = await api.create('api/billing/coupons/claim', {
                        code: formValues.code,
                    })
                    actions.setClaimed(true)
                    actions.setClaimedDetails(res)
                    actions.loadCouponsOverview()
                    posthog.capture('billing coupon claimed', {
                        campaign: props.campaign,
                        code: formValues.code,
                    })
                } catch (error: any) {
                    lemonToast.error(error.detail || 'Failed to claim coupon')
                    posthog.capture('billing coupon claim failed', {
                        campaign: props.campaign,
                        code: formValues.code,
                        error: error.detail || 'Unknown error',
                    })
                    throw error
                }
            },
        },
    })),
    listeners(({ values, actions }) => ({
        loadBillingSuccess: () => {
            // kea-forms errors() is a selector that only recalculates when form state changes.
            // Since we depend on external billing state, we force recalculation by re-setting a form value.
            actions.setCouponValue('code', values.coupon.code)
        },
    })),
    afterMount(({ actions }) => {
        actions.loadCouponsOverview()
    }),
])
