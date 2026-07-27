import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { OnboardingStepKey, SDKKey } from '~/types'

export type AdvertiseMobileReplayContext =
    | 'product-analytics-onboarding'
    | 'flags-onboarding'
    | 'experiments-onboarding'

export function AdvertiseMobileReplay({
    context,
    sdkKey,
}: {
    context: AdvertiseMobileReplayContext
    sdkKey: SDKKey
}): JSX.Element {
    let platform = 'Mobile'
    switch (sdkKey) {
        case SDKKey.ANDROID:
            platform = 'Android'
            break
        case SDKKey.IOS:
            platform = 'iOS'
            break
        case SDKKey.REACT_NATIVE:
            platform = 'React Native'
            break
        case SDKKey.FLUTTER:
            platform = 'Flutter'
            break
    }
    const dataAttrPlatform = platform.toLowerCase().replace(/\s+/g, '-')

    return (
        <div>
            <LemonDivider className="my-8" />
            <LemonBanner type="info">
                <h3>
                    Session Replay for {platform} <LemonTag type="highlight">NEW</LemonTag>
                </h3>
                <div>
                    Session replay is now in general availability for {platform}.{' '}
                    <Link
                        to={urls.onboarding({
                            productKey: 'session_replay',
                            stepKey: OnboardingStepKey.INSTALL,
                            sdk: sdkKey,
                        })}
                        data-attr={`${context}-${dataAttrPlatform}-replay-cta`}
                    >
                        Learn how to set it up
                    </Link>
                </div>
            </LemonBanner>
        </div>
    )
}
