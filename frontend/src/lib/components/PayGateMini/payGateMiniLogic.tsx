import { actions, connect, kea, key, path, props, selectors } from 'kea'
import { billingLogic } from 'scenes/billing/billingLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature } from '~/types'

import type { payGateMiniLogicType } from './payGateMiniLogicType'

export interface PayGateMiniLogicProps {
    featureKey: AvailableFeature
    currentUsage?: number
}

export type GateVariantType = 'add-card' | 'contact-sales' | 'move-to-cloud' | null

export const payGateMiniLogic = kea<payGateMiniLogicType>([
    props({} as PayGateMiniLogicProps),
    path(['lib', 'components', 'payGateMini', 'payGateMiniLogic']),
    key((props) => props.featureKey),
    connect(() => ({
        values: [
            billingLogic,
            ['billing', 'billingLoading'],
            userLogic,
            ['user', 'hasAvailableFeature', 'availableFeature'],
            preflightLogic,
            ['isCloudOrDev'],
        ],
        actions: [],
    })),
    actions({
        setGateVariant: (gateVariant: GateVariantType) => ({ gateVariant }),
    }),
    selectors(({ values, props }) => ({
        productWithFeature: [
            (s) => [s.billing],
            (billing) =>
                billing?.products?.find((product) => product.features?.some((f) => f.key === props.featureKey)),
        ],
        featureInfo: [
            (s) => [s.productWithFeature],
            (productWithFeature) => productWithFeature?.features.find((f) => f.key === props.featureKey),
        ],
        featureAvailableOnOrg: [
            (s) => [s.user, (_, props) => props.featureKey],
            (_user, featureKey) => {
                return values.availableFeature(featureKey)
            },
        ],
        minimumPlanWithFeature: [
            (s) => [s.productWithFeature],
            (productWithFeature) =>
                productWithFeature?.plans.find((plan) => plan.features?.some((f) => f.key === props.featureKey)),
        ],
        gateVariant: [
            (s) => [
                s.billingLoading,
                s.hasAvailableFeature,
                s.minimumPlanWithFeature,
                (_, props) => props.featureKey,
                (_, props) => props.currentUsage,
            ],
            (billingLoading, hasAvailableFeature, minimumPlanWithFeature, featureKey, currentUsage) => {
                if (hasAvailableFeature(featureKey, currentUsage)) {
                    return null
                }
                if (billingLoading) {
                    return null
                }
                if (values.isCloudOrDev) {
                    if (!minimumPlanWithFeature || minimumPlanWithFeature.contact_support) {
                        return 'contact-sales'
                    } else {
                        return 'add-card'
                    }
                } else {
                    return 'move-to-cloud'
                }
            },
        ],
    })),
])
