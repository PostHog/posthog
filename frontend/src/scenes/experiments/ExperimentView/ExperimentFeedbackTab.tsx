import { useActions, useValues } from 'kea'

import { IconArrowRight } from '@posthog/icons'
import { LemonBanner, Link, Spinner } from '@posthog/lemon-ui'

import { FeedbackTabContent } from 'scenes/surveys/FeedbackTabContent'
import { QuickSurveyType } from 'scenes/surveys/quick-create/types'
import { SurveysTabs } from 'scenes/surveys/surveysLogic'
import { urls } from 'scenes/urls'

import { Experiment } from '~/types'

import { experimentFeedbackTabLogic } from './experimentFeedbackTabLogic'

export function ExperimentFeedbackTab({ experiment }: { experiment: Experiment }): JSX.Element {
    const logic = experimentFeedbackTabLogic({ experiment })
    const { experimentSurveys, experimentSurveysLoaded, experimentSurveysLoading, experimentSurveysLoadFailed } =
        useValues(logic)
    const { loadExperimentSurveys } = useActions(logic)

    if (!experimentSurveysLoaded || experimentSurveysLoading) {
        return (
            <div className="flex items-center justify-center py-8">
                <Spinner className="text-2xl" />
            </div>
        )
    }

    if (experimentSurveysLoadFailed) {
        return (
            <LemonBanner type="error" action={{ children: 'Try again', onClick: loadExperimentSurveys }}>
                Couldn't load the surveys for this experiment.
            </LemonBanner>
        )
    }

    return (
        <>
            {/* A reset experiment is a draft whose flag stays active, so its surveys keep showing */}
            {!experiment.start_date && !experiment.feature_flag?.active && (
                <LemonBanner type="info" className="mb-6" data-attr="experiment-feedback-draft-note">
                    This experiment hasn't launched yet. Surveys linked to it start showing to users once it launches.
                </LemonBanner>
            )}
            <FeedbackTabContent
                surveys={experimentSurveys}
                context={{
                    type: QuickSurveyType.EXPERIMENT,
                    experiment,
                }}
                emptyStateHeader="Survey your experiment participants"
                emptyStateDescription="Create a survey that targets users exposed to this experiment. Responses are linked to the experiment so you can review them alongside your results."
                multipleSurveysBannerMessage={
                    <>
                        Showing only surveys associated with this experiment.{' '}
                        <Link to={urls.surveys(SurveysTabs.Active)}>
                            See all surveys <IconArrowRight />
                        </Link>
                    </>
                }
            />
        </>
    )
}
