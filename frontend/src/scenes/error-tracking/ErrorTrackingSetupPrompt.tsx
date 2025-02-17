import { IconExternal } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import posthog from 'posthog-js'
import { teamLogic } from 'scenes/teamLogic'

import { ProductKey } from '~/types'

import { errorTrackingLogic } from './errorTrackingLogic'

export const ErrorTrackingSetupPrompt = ({ children }: { children: React.ReactElement }): JSX.Element => {
    const { hasSentExceptionEvent, hasSentExceptionEventLoading } = useValues(errorTrackingLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const hasErrorTracking = useFeatureFlag('ERROR_TRACKING')

    const exceptionAutocaptureEnabled = currentTeam && currentTeam.autocapture_exceptions_opt_in

    return hasSentExceptionEventLoading || currentTeamLoading ? (
        <div className="flex justify-center">
            <Spinner />
        </div>
    ) : !hasErrorTracking ? (
        <BetaAccessBanner />
    ) : !hasSentExceptionEvent && !exceptionAutocaptureEnabled ? (
        <IngestionStatusCheck />
    ) : (
        children
    )
}

const IngestionStatusCheck = (): JSX.Element | null => {
    const { updateCurrentTeam } = useActions(teamLogic)

    return (
        <ProductIntroduction
            productName="Error tracking"
            thingName="issue"
            titleOverride="You haven't captured any exceptions"
            description="To start capturing exceptions you need to enable exception autocapture. Exception autocapture only applies to the JS SDK. Installation for other platforms are described in the docs."
            isEmpty={true}
            productKey={ProductKey.ERROR_TRACKING}
            actionElementOverride={
                <>
                    <LemonButton
                        type="primary"
                        onClick={() => updateCurrentTeam({ autocapture_exceptions_opt_in: true })}
                    >
                        Enable exception autocapture
                    </LemonButton>
                    <LemonButton
                        targetBlank
                        sideIcon={<IconExternal className="w-5 h-5" />}
                        to="https://posthog.com/docs/error-tracking/installation"
                    >
                        Read the docs
                    </LemonButton>
                </>
            }
        />
    )
}

const BetaAccessBanner = (): JSX.Element | null => {
    return (
        <ProductIntroduction
            productName="Error tracking"
            thingName="issue"
            titleOverride="Welcome to Error Tracking"
            description="Error tracking is in beta for our JS, Node and Python SDKs."
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
