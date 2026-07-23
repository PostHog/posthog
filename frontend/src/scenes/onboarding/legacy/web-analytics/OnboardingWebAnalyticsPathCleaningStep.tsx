import { useValues } from 'kea'

import { PathCleaningSuggestionsBanner } from 'scenes/settings/environment/PathCleaningSuggestionsBanner'
import { pathCleaningSuggestionsLogic } from 'scenes/settings/environment/pathCleaningSuggestionsLogic'

import { OnboardingStepKey } from '~/types'

import { OnboardingStepComponentType } from '../onboardingLogic'
import { OnboardingStep } from '../OnboardingStep'

export const OnboardingWebAnalyticsPathCleaningStep: OnboardingStepComponentType = () => {
    const { latestSuggestion, suggestionsLoading } = useValues(pathCleaningSuggestionsLogic)

    return (
        <OnboardingStep title="Clean up your paths" stepKey={OnboardingStepKey.PATH_CLEANING} showSkip>
            <p>
                When your site has dynamic URLs like <code>/users/123</code> and <code>/users/456</code>, Web analytics
                shows them as separate rows. Path cleaning rules collapse them into one readable template (
                <code>/users/&lt;id&gt;</code>).
            </p>
            {latestSuggestion ? (
                <>
                    <p>We analyzed your traffic and prepared a few rules for you:</p>
                    <PathCleaningSuggestionsBanner />
                </>
            ) : (
                <p className="text-secondary">
                    {suggestionsLoading
                        ? 'Looking for path patterns in your traffic…'
                        : "Once we've seen enough traffic we'll suggest path cleaning rules here. You can always add them later in project settings."}
                </p>
            )}
        </OnboardingStep>
    )
}

OnboardingWebAnalyticsPathCleaningStep.stepKey = OnboardingStepKey.PATH_CLEANING
