import { Link } from 'lib/lemon-ui/Link'
import { SDKFeatureAnnouncementBanner } from './sdk-install-instructions/components/SDKFeatureAnnouncementBanner'
import { ProductKey, SDK, SDKKey } from '~/types'

export const SDKSnippet = ({
    sdk,
    sdkInstructions,
    productKey,
}: {
    sdk: SDK
    sdkInstructions: () => JSX.Element
    productKey: ProductKey
}): JSX.Element => {
    return (
        <div>
            <div className="mb-8">
                <h3 className="text-xl font-bold mb-2">Integrate PostHog with {sdk.name}</h3>
                <Link className="" to={sdk.docsLink} target="_blank" targetBlankIcon disableDocsPanel>
                    Read the docs
                </Link>
            </div>
            <div className="deprecated-space-y-4">{sdkInstructions()}</div>
            <div className="deprecated-space-y-4">
                {/* Only show survey announcements in non surveys product context */}
                {productKey !== ProductKey.SURVEYS && (
                    <>
                        {sdk.key === SDKKey.REACT_NATIVE && <AdvertiseSurveysReactNativeBeta productKey={productKey} />}
                        {sdk.key === SDKKey.IOS && <AdvertiseSurveysIOSBeta productKey={productKey} />}
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
function AdvertiseSurveysReactNativeBeta({ productKey }: { productKey: ProductKey }): JSX.Element {
    return (
        <SDKFeatureAnnouncementBanner
            context={`${productKey.toLowerCase()}-onboarding`}
            sdkKey={SDKKey.REACT_NATIVE}
            featureName="Surveys"
            tagText="Beta"
            tagType="highlight"
            productKey="surveys"
            description="Surveys is now available for React Native as Beta."
            linkText="Learn how to set it up"
        />
    )
}

function AdvertiseSurveysIOSBeta({ productKey }: { productKey: ProductKey }): JSX.Element {
    return (
        <SDKFeatureAnnouncementBanner
            context={`${productKey.toLowerCase()}-onboarding`}
            sdkKey={SDKKey.IOS}
            featureName="Surveys"
            tagText="Beta"
            tagType="highlight"
            productKey="surveys"
            description="Surveys is now available for iOS as Beta."
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
