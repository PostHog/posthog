import { useActions, useValues } from 'kea'

import { IconInfo, IconWarning } from '@posthog/icons'
import { Button, Item, ItemActions, ItemContent, ItemDescription, ItemMedia, Spinner } from '@posthog/quill'

import { FeedbackTabContent } from 'scenes/surveys/FeedbackTabContent'
import { QuickSurveyType } from 'scenes/surveys/quick-create/types'

import { Experiment } from '~/types'

import {
    FEEDBACK_DRAFT_NOTE,
    FEEDBACK_EMPTY_DESCRIPTION,
    FEEDBACK_EMPTY_HEADER,
    FEEDBACK_LOAD_ERROR,
    FeedbackSurveysNote,
} from './ExperimentFeedbackTab'
import { experimentFeedbackTabLogic } from './experimentFeedbackTabLogic'

export function QuillExperimentFeedbackTab({ experiment }: { experiment: Experiment }): JSX.Element {
    const logic = experimentFeedbackTabLogic({ experiment })
    const { experimentSurveys, experimentSurveysLoaded, experimentSurveysLoading, experimentSurveysLoadFailed } =
        useValues(logic)
    const { loadExperimentSurveys } = useActions(logic)

    if (!experimentSurveysLoaded || experimentSurveysLoading) {
        return (
            <div className="flex items-center justify-center py-8">
                <Spinner />
            </div>
        )
    }

    if (experimentSurveysLoadFailed) {
        return (
            <Item variant="outline" size="sm" tone="destructive">
                <ItemMedia variant="icon" aria-hidden>
                    <IconWarning />
                </ItemMedia>
                <ItemContent>
                    <ItemDescription className="line-clamp-none">{FEEDBACK_LOAD_ERROR}</ItemDescription>
                </ItemContent>
                <ItemActions>
                    <Button variant="outline" onClick={loadExperimentSurveys}>
                        Try again
                    </Button>
                </ItemActions>
            </Item>
        )
    }

    return (
        <div className="flex flex-col gap-6">
            {/* A reset experiment is a draft whose flag stays active, so its surveys keep showing */}
            {!experiment.start_date && !experiment.feature_flag?.active && (
                <Item variant="outline" size="sm" tone="info" data-attr="experiment-feedback-draft-note">
                    <ItemMedia variant="icon" aria-hidden>
                        <IconInfo />
                    </ItemMedia>
                    <ItemContent>
                        <ItemDescription className="line-clamp-none">{FEEDBACK_DRAFT_NOTE}</ItemDescription>
                    </ItemContent>
                </Item>
            )}
            <FeedbackTabContent
                surveys={experimentSurveys}
                context={{ type: QuickSurveyType.EXPERIMENT, experiment }}
                emptyStateHeader={FEEDBACK_EMPTY_HEADER}
                emptyStateDescription={FEEDBACK_EMPTY_DESCRIPTION}
                multipleSurveysBannerMessage={<FeedbackSurveysNote />}
            />
        </div>
    )
}
