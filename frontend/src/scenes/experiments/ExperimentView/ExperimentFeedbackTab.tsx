import { useValues } from 'kea'

import { IconArrowRight } from '@posthog/icons'
import { Link, Spinner } from '@posthog/lemon-ui'

import { FeedbackTabContent } from 'scenes/surveys/FeedbackTabContent'
import { QuickSurveyType } from 'scenes/surveys/quick-create/types'
import { SurveysTabs, surveysLogic } from 'scenes/surveys/surveysLogic'
import { urls } from 'scenes/urls'

import { Experiment } from '~/types'

export function ExperimentFeedbackTab({ experiment }: { experiment: Experiment }): JSX.Element {
    const { data, dataLoading } = useValues(surveysLogic)

    const linkedFlagId = experiment.feature_flag?.id
    const surveysForExperiment = linkedFlagId ? data.surveys.filter((s) => s.linked_flag_id === linkedFlagId) : []

    if (dataLoading) {
        return (
            <div className="flex items-center justify-center py-8">
                <Spinner className="text-2xl" />
            </div>
        )
    }

    return (
        <FeedbackTabContent
            surveys={surveysForExperiment}
            context={{
                type: QuickSurveyType.EXPERIMENT,
                experiment,
            }}
            emptyStateBannerMessage="Gather qualitative feedback from users participating in this experiment"
            multipleSurveysBannerMessage={
                <>
                    Showing only surveys associated with this experiment.{' '}
                    <Link to={urls.surveys(SurveysTabs.Active)}>
                        See all surveys <IconArrowRight />
                    </Link>
                </>
            }
        />
    )
}
