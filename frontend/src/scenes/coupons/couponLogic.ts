import { actions, connect, kea, path, props, reducers } from 'kea'
import { forms } from 'kea-forms'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { billingLogic } from 'scenes/billing/billingLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import type { couponLogicType } from './couponLogicType'

export interface CouponLogicProps {
    campaign: string
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
            ['billing'],
        ],
    })),
    actions({
        setClaimed: (claimed: boolean) => ({ claimed }),
        setClaimedDetails: (details: any) => ({ details }),
    }),
    reducers({
        claimed: [false, { setClaimed: (_, { claimed }) => claimed }],
        claimedDetails: [null as any, { setClaimedDetails: (_, { details }) => details }],
    }),
    forms(({ values, actions, props }) => ({
        coupon: {
            defaults: {
                code: '',
                organization_name: values.currentOrganization?.name || '',
            } as CouponFormValues,
            errors: ({ code }) => {
                if (!values.billing?.has_active_subscription) {
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
                    posthog.capture('billing coupon claimed', {
                        campaign: props.campaign,
                        code: formValues.code,
                    })
                } catch (error: any) {
                    lemonToast.error(error.detail || 'Failed to claim coupon')
                    throw error
                }
            },
        },
    })),
])
