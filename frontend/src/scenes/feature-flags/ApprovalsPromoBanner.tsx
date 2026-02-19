import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import { JudgeHog } from 'lib/components/hedgehogs'
import { lemonBannerLogic } from 'lib/lemon-ui/LemonBanner/lemonBannerLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature } from '~/types'

const DISMISS_KEY = 'feature-flags-approvals-promo'

export function ApprovalsPromoBanner(): JSX.Element | null {
    const { hasAvailableFeature } = useValues(userLogic)
    const { isAdminOrOwner } = useValues(organizationLogic)
    const bannerLogic = lemonBannerLogic({ dismissKey: DISMISS_KEY })
    const { isDismissed } = useValues(bannerLogic)
    const { dismiss } = useActions(bannerLogic)

    const shouldShow = isAdminOrOwner && hasAvailableFeature(AvailableFeature.APPROVALS)

    useEffect(() => {
        if (shouldShow && !isDismissed) {
            posthog.capture('feature flags approvals promo shown')
        }
    }, [shouldShow, isDismissed])

    if (!shouldShow || isDismissed) {
        return null
    }

    return (
        <LemonBanner type="info" hideIcon>
            <div className="flex flex-row gap-8 px-8 py-3 items-center justify-evenly">
                <div>
                    <h3 className="mb-1 text-lg font-semibold">Stop yolo-shipping flag changes</h3>
                    <p className="mb-3">
                        Require a second pair of eyes before feature flags go live. Because "I swear I only changed one
                        condition" is not a rollback strategy.
                    </p>
                    <div className="flex flex-row gap-2">
                        <LemonButton
                            type="primary"
                            className="w-fit"
                            to={urls.approvals()}
                            onClick={() => posthog.capture('feature flags approvals promo cta clicked')}
                        >
                            Set up approvals
                        </LemonButton>
                        <LemonButton
                            type="tertiary"
                            onClick={() => {
                                posthog.capture('feature flags approvals promo dismissed')
                                dismiss()
                            }}
                        >
                            I'm not interested
                        </LemonButton>
                    </div>
                </div>
                <JudgeHog className="h-30 w-fit shrink-0" alt="Judge hedgehog illustration" />
            </div>
        </LemonBanner>
    )
}
