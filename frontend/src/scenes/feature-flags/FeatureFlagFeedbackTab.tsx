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
            emptyStateBannerMessage="Gather valuable insights by automatically displaying a survey to users in this feature flag"
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
