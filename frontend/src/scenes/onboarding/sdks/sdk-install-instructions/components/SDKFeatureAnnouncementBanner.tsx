import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonTagType } from 'lib/lemon-ui/LemonTag'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { OnboardingStepKey, SDKKey } from '~/types'

const platformNames: Partial<Record<SDKKey, string>> = {
    [SDKKey.ANDROID]: 'Android',
    [SDKKey.IOS]: 'iOS',
    [SDKKey.REACT_NATIVE]: 'React Native',
    [SDKKey.FLUTTER]: 'Flutter',
    [SDKKey.JS_WEB]: 'JavaScript',
    [SDKKey.REACT]: 'React',
    // Add other platforms as needed
}

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
    let platform =
        platformNames[sdkKey] ||
        sdkKey.replace(/_(\w)/g, (_, letter) => ` ${letter.toUpperCase()}`).replace(/^\w/, (c) => c.toUpperCase())

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
