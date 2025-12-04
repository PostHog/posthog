import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { router, urlToAction } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { couponLogic } from 'scenes/coupons/couponLogic'
import { urls } from 'scenes/urls'

import type { onboardingCouponLogicType } from './onboardingCouponLogicType'

export interface OnboardingCouponLogicProps {
    campaign: string
}

export const onboardingCouponLogic = kea<onboardingCouponLogicType>([
    path(['scenes', 'onboarding', 'coupon', 'onboardingCouponLogic']),
    props({} as OnboardingCouponLogicProps),
    connect((props: OnboardingCouponLogicProps) => ({
        values: [
            couponLogic({ campaign: props.campaign }),
            ['claimed', 'claimedDetails', 'getClaimedCouponForCampaign'],
            featureFlagLogic,
            ['featureFlags'],
        ],
    })),
    actions({
        setCampaign: (campaign: string) => ({ campaign }),
        continueToOnboarding: true,
        skipCoupon: true,
    }),
    reducers(({ props }) => ({
        campaign: [
            props.campaign || '',
            {
                setCampaign: (_, { campaign }) => campaign,
            },
        ],
    })),
    selectors({
        alreadyClaimed: [
            (s) => [s.getClaimedCouponForCampaign, s.campaign],
            (getClaimedCouponForCampaign, campaign) => getClaimedCouponForCampaign(campaign),
        ],
        shouldContinueAfterClaim: [
            (s) => [s.claimed, s.alreadyClaimed],
            (claimed, alreadyClaimed) => claimed || alreadyClaimed,
        ],
    }),
    listeners(({ values }) => ({
        continueToOnboarding: () => {
            const useUseCaseSelection = values.featureFlags[FEATURE_FLAGS.ONBOARDING_USE_CASE_SELECTION] === 'test'
            const nextUrl = router.values.searchParams.next

            if (useUseCaseSelection) {
                router.actions.push(urls.useCaseSelection(), nextUrl ? { next: nextUrl } : undefined)
            } else {
                router.actions.push(urls.products(), nextUrl ? { next: nextUrl } : undefined)
            }
        },
        skipCoupon: () => {
            const useUseCaseSelection = values.featureFlags[FEATURE_FLAGS.ONBOARDING_USE_CASE_SELECTION] === 'test'
            const nextUrl = router.values.searchParams.next

            if (useUseCaseSelection) {
                router.actions.push(urls.useCaseSelection(), nextUrl ? { next: nextUrl } : undefined)
            } else {
                router.actions.push(urls.products(), nextUrl ? { next: nextUrl } : undefined)
            }
        },
    })),
    urlToAction(({ actions }) => ({
        '/onboarding/coupon/:campaign': ({ campaign }) => {
            if (campaign) {
                actions.setCampaign(campaign)
            }
        },
    })),
])
