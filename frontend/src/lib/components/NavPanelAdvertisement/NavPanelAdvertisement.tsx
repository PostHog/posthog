import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconX } from '@posthog/icons'
import { Link, Tooltip } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { availableOnboardingProducts } from 'scenes/onboarding/utils'
import { getProductIcon } from 'scenes/products/Products'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { FlaggedFeature } from '../FlaggedFeature'
import { navPanelAdvertisementLogic } from './NavPanelAdvertisementLogic'

type Payload = {
    product_key: string
    header?: string
    text?: string
    docs_link?: string
    app_link?: string
    product_info_link?: string
}

export function NavPanelAdvertisement(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)

    if (featureFlags[FEATURE_FLAGS.TARGETED_PRODUCT_UPSELL] === 'control') {
        return null
    }

    return (
        <FlaggedFeature
            flag={FEATURE_FLAGS.TARGETED_PRODUCT_UPSELL}
            children={(_flagValue, payload: Payload) => {
                if (payload === undefined) {
                    return null
                }
                return <NavPanelAdvertisementContent payload={payload} />
            }}
        />
    )
}

export function NavPanelAdvertisementContent({ payload }: { payload: Payload }): JSX.Element | null {
    const product = availableOnboardingProducts[payload.product_key as keyof typeof availableOnboardingProducts]
    const logic = navPanelAdvertisementLogic({ productKey: payload.product_key })
    const { hideAdvertisement } = useActions(logic)
    const { hidden } = useValues(logic)

    if (hidden || (!product && !payload.header)) {
        return null
    }

    return (
        <div className="w-full my-1">
            <Tooltip
                title="Based on your usage we think you might like this other product
                            we have, so we're gently bringing it to your attention :) Feel free to 
                            dismiss it to make it go away."
            >
                <p className="text-xxs text-muted mb-1 p-0 text-right">ads via PostHog</p>
            </Tooltip>
            <Link
                to={payload.app_link}
                className="text-primary"
                onClick={() => {
                    posthog.capture('nav panel advertisement clicked', {
                        product_key: payload.product_key,
                        payload,
                    })
                }}
            >
                <div className="border rounded bg-primary text-xs *:flex *:gap-2 *:px-2 *:py-1">
                    <div className=" justify-between mt-1">
                        <div className="flex items-center gap-2">
                            {product && getProductIcon(product.iconColor, product.icon, 'text-lg')}
                            <strong>{payload.header || product?.name}</strong>
                        </div>
                        <LemonButton
                            icon={<IconX className="text-muted" />}
                            tooltip="Dismiss"
                            tooltipPlacement="right"
                            size="xxsmall"
                            onClick={(e) => {
                                e.preventDefault()
                                e.stopPropagation()
                                posthog.capture('nav panel advertisement dismissed', {
                                    product_key: payload.product_key,
                                    payload,
                                })
                                hideAdvertisement()
                            }}
                            noPadding
                        />
                    </div>

                    <div className="flex flex-col gap-1">
                        <p className="mb-0">{payload.text}</p>
                        <p className="mb-0">
                            <Link
                                onClick={(e) => {
                                    e.preventDefault()
                                    posthog.capture('nav panel advertisement learn more clicked', {
                                        product_key: payload.product_key,
                                        payload,
                                    })
                                    window.open(payload.product_info_link, '_blank')
                                }}
                            >
                                Learn more
                            </Link>{' '}
                            &middot;{' '}
                            <Link
                                to={payload.docs_link}
                                onClick={(e) => {
                                    e.preventDefault()
                                    sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Docs, payload.docs_link)
                                    posthog.capture('nav panel advertisement docs clicked', {
                                        product_key: payload.product_key,
                                        payload,
                                    })
                                }}
                            >
                                Docs
                            </Link>
                        </p>
                    </div>
                </div>
            </Link>
        </div>
    )
}
