import { LemonSelect } from '@posthog/lemon-ui'

import { Survey, SurveyType } from '~/types'

import {defaultSurveyAppearance, NewSurvey} from './constants'
import { SurveyAPIEditor } from './SurveyAPIEditor'
import { SurveyAppearancePreview } from './SurveyAppearancePreview'
import {useValues} from "kea";
import {teamLogic} from "scenes/teamLogic";

interface SurveyFormAppearanceProps {
    previewPageIndex: number
    survey: NewSurvey | Survey
    handleSetSelectedPageIndex: (activePreview: number) => void
    isEditingSurvey?: boolean
}

export function SurveyFormAppearance({
    previewPageIndex,
    survey,
    handleSetSelectedPageIndex,
}: SurveyFormAppearanceProps): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const surveyAppearance = {
            ...currentTeam?.survey_config?.appearance,
    }

    return survey.type !== SurveyType.API ? (
        <div className="survey-view max-w-72">
            <SurveyAppearancePreview surveyAppearance={surveyAppearance} survey={survey as Survey} previewPageIndex={previewPageIndex} />
            <LemonSelect
                onChange={(pageIndex) => handleSetSelectedPageIndex(pageIndex)}
                className="mt-4 whitespace-nowrap"
                fullWidth
                value={previewPageIndex}
                options={[
                    ...survey.questions.map((question, index) => ({
                        label: `${index + 1}. ${question.question ?? ''}`,
                        value: index,
                    })),
                    ...(survey.appearance?.displayThankYouMessage
                        ? [
                              {
                                  label: `${survey.questions.length + 1}. Confirmation message`,
                                  value: survey.questions.length,
                              },
                          ]
                        : []),
                ]}
            />
        </div>
    ) : (
        <div className="flex flex-col">
            <h4 className="text-center">API survey response</h4>
            <SurveyAPIEditor survey={survey} />
        </div>
    )
}
