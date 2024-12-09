import { LemonButton } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { ProductKey } from '~/types'

export const AlphaAccessScenePrompt = ({ children }: { children: React.ReactElement }): JSX.Element => {
    const hasErrorTracking = useFeatureFlag('ERROR_TRACKING')
    const { openSupportForm } = useActions(supportLogic)

    return !hasErrorTracking ? (
        children
    ) : (
        <ProductIntroduction
            productName="Error tracking"
            thingName="issue"
            titleOverride="Capture your first exception"
            description="Error tracking is in closed alpha right now but we are onboarding customers. Right now we only support the JS and Python SDKs."
            isEmpty={true}
            actionElementOverride={
                <LemonButton
                    type="primary"
                    onClick={() =>
                        openSupportForm({
                            target_area: 'error_tracking',
                            isEmailFormOpen: true,
                            message: 'Hi\n\nI would like to request access to the error tracking product',
                            severity_level: 'low',
                        })
                    }
                >
                    Get access
                </LemonButton>
            }
            productKey={ProductKey.ERROR_TRACKING}
        />
    )
}
