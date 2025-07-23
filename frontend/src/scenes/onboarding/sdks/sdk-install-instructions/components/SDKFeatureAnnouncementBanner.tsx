import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonTagType } from 'lib/lemon-ui/LemonTag'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'
import { SDKKey, OnboardingStepKey } from '~/types'

export type SDKFeatureAnnouncementBannerProps = {
    context: string
    sdkKey: SDKKey
    featureName: string
    tagText?: string
    tagType?: LemonTagType
    productKey: string
    stepKey?: OnboardingStepKey
    description?: string
    bannerType?: 'info' | 'warning' | 'error' | 'success'
    linkText?: string
    showDivider?: boolean
}

/**
 * A reusable component for displaying feature announcements for different SDKs
 */
export function SDKFeatureAnnouncementBanner({
    context,
    sdkKey,
    featureName,
    tagText = 'NEW',
    tagType = 'highlight',
    productKey,
    stepKey = OnboardingStepKey.INSTALL,
    description,
    bannerType = 'info',
    linkText = 'Learn how to set it up',
    showDivider = true,
}: SDKFeatureAnnouncementBannerProps): JSX.Element {
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
        case SDKKey.JS_WEB:
            platform = 'JavaScript'
            break
        case SDKKey.REACT:
            platform = 'React'
            break
        // Add other platforms as needed
        default:
            platform = sdkKey.replace(/_/g, ' ')
    }

    const defaultDescription = `${featureName} is now available for ${platform}.`

    // for data attributes
    const platformSlug = platform.toLowerCase().replace(/\s+/g, '-')
    const featureSlug = featureName.toLowerCase().replace(/\s+/g, '-')
    const contextSlug = context.toLowerCase().replace(/\s+/g, '-')
    const dataAttr = `${contextSlug}-${platformSlug}-${featureSlug}-cta`

    return (
        <div>
            {showDivider && <LemonDivider className="my-8" />}
            <LemonBanner type={bannerType}>
                <h3>
                    {featureName} for {platform} {tagText && <LemonTag type={tagType}>{tagText}</LemonTag>}
                </h3>
                <div>
                    {description || defaultDescription}{' '}
                    <Link to={urls.onboarding(productKey, stepKey, sdkKey)} data-attr={dataAttr}>
                        {linkText}
                    </Link>
                </div>
            </LemonBanner>
        </div>
    )
}
