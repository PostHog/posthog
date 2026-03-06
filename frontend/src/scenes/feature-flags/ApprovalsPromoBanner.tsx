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
        <LemonBanner type="info" hideIcon className="bg-transparent border-dashed border-2">
            <div className="flex items-center gap-8 w-full justify-center p-4">
                <div className="w-30 shrink-0 hidden md:block">
                    <JudgeHog className="w-full h-full" />
                </div>
                <div className="flex-shrink max-w-140">
                    <h2>Stop YOLO-shipping flag changes</h2>
                    <p>
                        Require a second pair of eyes before feature flags go live. Because "I swear I only changed one
                        condition" is not a rollback strategy.
                    </p>
                    <div className="flex items-center gap-x-4 gap-y-2 mt-6 flex-wrap">
                        <LemonButton
                            type="primary"
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
                            Not interested
                        </LemonButton>
                    </div>
                </div>
            </div>
        </LemonBanner>
    )
}
