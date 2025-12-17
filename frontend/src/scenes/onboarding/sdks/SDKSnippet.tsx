import { Link } from 'lib/lemon-ui/Link'

import { ProductKey } from '~/queries/schema/schema-general'
import { SDK, SDKKey } from '~/types'

import { MCPInstallBanner } from './sdk-install-instructions/components/MCPInstallBanner'
import { SDKFeatureAnnouncementBanner } from './sdk-install-instructions/components/SDKFeatureAnnouncementBanner'

// SDKs that have wizard support
const SDKS_WITH_WIZARD = [SDKKey.REACT, SDKKey.NEXT_JS, SDKKey.SVELTE, SDKKey.REACT_NATIVE, SDKKey.ASTRO]

export const SDKSnippet = ({
    sdk,
    sdkInstructions,
    productKey,
}: {
    sdk: SDK
    sdkInstructions: () => JSX.Element
    productKey: ProductKey
}): JSX.Element => {
    const hasWizardSupport = SDKS_WITH_WIZARD.includes(sdk.key as SDKKey)

    return (
        <div>
            <div className="mb-8">
                <h3 className="text-xl font-bold mb-2">Integrate PostHog with {sdk.name}</h3>
                <Link className="" to={sdk.docsLink} target="_blank" targetBlankIcon disableDocsPanel>
                    Read the docs
                </Link>
            </div>
            {!hasWizardSupport && <MCPInstallBanner variant="sdk" />}
            <div className="deprecated-space-y-4">{sdkInstructions()}</div>
            <div className="deprecated-space-y-4">
                {/* Only show survey announcements in non surveys product context */}
                {productKey !== ProductKey.SURVEYS && (
                    <>
                        {sdk.key === SDKKey.REACT_NATIVE && <AdvertiseSurveysReactNative productKey={productKey} />}
                        {sdk.key === SDKKey.IOS && <AdvertiseSurveysIOS productKey={productKey} />}
                        {sdk.key === SDKKey.FLUTTER && <AdvertiseSurveysFlutterBeta productKey={productKey} />}
                    </>
                )}
            </div>
        </div>
    )
}

/**
 * Local components to advertise SDK Features
 */
function AdvertiseSurveysReactNative({ productKey }: { productKey: ProductKey }): JSX.Element {
    return (
        <SDKFeatureAnnouncementBanner
            context={`${productKey.toLowerCase()}-onboarding`}
            sdkKey={SDKKey.REACT_NATIVE}
            featureName="Surveys"
            tagText="GA"
            tagType="primary"
            productKey="surveys"
            description="Surveys is now available for React Native."
            linkText="Learn how to set it up"
        />
    )
}

function AdvertiseSurveysIOS({ productKey }: { productKey: ProductKey }): JSX.Element {
    return (
        <SDKFeatureAnnouncementBanner
            context={`${productKey.toLowerCase()}-onboarding`}
            sdkKey={SDKKey.IOS}
            featureName="Surveys"
            tagText="GA"
            tagType="primary"
            productKey="surveys"
            description="Surveys is now available for iOS."
            linkText="Learn how to set it up"
        />
    )
}

function AdvertiseSurveysFlutterBeta({ productKey }: { productKey: ProductKey }): JSX.Element {
    return (
        <SDKFeatureAnnouncementBanner
            context={`${productKey.toLowerCase()}-onboarding`}
            sdkKey={SDKKey.FLUTTER}
            featureName="Surveys"
            tagText="Beta"
            tagType="highlight"
            productKey="surveys"
            description="Surveys is now available for Flutter as Beta (iOS only)."
            linkText="Learn how to set it up"
        />
    )
}
