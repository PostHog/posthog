import { IconArrowRight } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { FeedbackTabContent } from 'scenes/surveys/FeedbackTabContent'
import { QuickSurveyType } from 'scenes/surveys/quick-create/types'
import { SurveysTabs } from 'scenes/surveys/surveysLogic'
import { urls } from 'scenes/urls'

import { FeatureFlagType } from '~/types'

export function FeedbackTab({ featureFlag }: { featureFlag: FeatureFlagType }): JSX.Element {
    const surveys = featureFlag.surveys || []

    return (
        <FeedbackTabContent
            surveys={surveys}
            context={{
                type: QuickSurveyType.FEATURE_FLAG,
                flag: featureFlag,
            }}
            emptyStateHeader="Survey users with this flag enabled"
            emptyStateDescription="Create a survey that targets users with this feature flag enabled. Responses are linked to the flag so you can review them alongside your rollout."
            multipleSurveysBannerMessage={
                <>
                    Showing only surveys associated with this feature flag.{' '}
                    <Link to={urls.surveys(SurveysTabs.Active)}>
                        See all surveys <IconArrowRight />
                    </Link>
                </>
            }
        />
    )
}
