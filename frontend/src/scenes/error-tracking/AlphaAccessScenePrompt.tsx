import { LemonButton } from '@posthog/lemon-ui'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import posthog from 'posthog-js'

import { ProductKey } from '~/types'

export const AlphaAccessScenePrompt = ({ children }: { children: React.ReactElement }): JSX.Element => {
    const hasErrorTracking = useFeatureFlag('ERROR_TRACKING')

    return hasErrorTracking ? (
        children
    ) : (
        <ProductIntroduction
            productName="Error tracking"
            thingName="issue"
            titleOverride="Welcome to Error Tracking"
            description="Error tracking is in closed alpha for our JS and Python SDKs. If you would like access please reach out and someone on our team will onboard you."
            isEmpty={true}
            docsURL="https://posthog.com/docs/error-tracking"
            productKey={ProductKey.ERROR_TRACKING}
            actionElementOverride={
                <LemonButton
                    type="primary"
                    onClick={() => posthog.updateEarlyAccessFeatureEnrollment('error-tracking', true)}
                >
                    Get started
                </LemonButton>
            }
        />
    )
}
