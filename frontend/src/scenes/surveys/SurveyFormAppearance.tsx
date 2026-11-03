import { useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { surveysLogic } from 'scenes/surveys/surveysLogic'

import { Survey, SurveyType } from '~/types'

import { NewSurvey } from './constants'
import { SurveyAPIEditor } from './SurveyAPIEditor'
import { SurveyAppearancePreview } from './SurveyAppearancePreview'
import { getNextPreviewPageIndex } from './surveyPreviewNavigation'
import { clampPreviewPageIndex, getFirstPreviewPageIndex, getIntroScreenPageOptions } from './utils'

interface SurveyFormAppearanceProps {
    previewPageIndex: number
    survey: NewSurvey | Survey
    handleSetSelectedPageIndex: (activePreview: number) => void
}

export function SurveyFormAppearance({
    previewPageIndex,
    survey,
    handleSetSelectedPageIndex,
}: SurveyFormAppearanceProps): JSX.Element | null {
    const { isAppearanceModalOpen } = useValues(surveysLogic)
    const effectivePageIndex = clampPreviewPageIndex(previewPageIndex, survey)

    if (isAppearanceModalOpen) {
        return null
    }

    return survey.type !== SurveyType.API ? (
        <div className="flex flex-col h-full gap-2 items-start flex-1 @min-[60rem]/main-content:pl-8">
            <SurveyAppearancePreview
                survey={survey as Survey}
                previewPageIndex={effectivePageIndex}
                onPreviewSubmit={(response) => {
                    const nextPageIndex = getNextPreviewPageIndex(survey, effectivePageIndex, response)
                    if (nextPageIndex !== null) {
                        handleSetSelectedPageIndex(nextPageIndex)
                    }
                }}
                onPreviewBack={() =>
                    handleSetSelectedPageIndex(Math.max(getFirstPreviewPageIndex(survey), effectivePageIndex - 1))
                }
            />
            <LemonField.Pure label="Current question" className="max-w-xs gap-1" htmlFor="current-question-select">
                <LemonSelect
                    onChange={(pageIndex) => handleSetSelectedPageIndex(pageIndex)}
                    id="current-question-select"
                    fullWidth
                    truncateText={{ maxWidthClass: 'max-w-60' }}
                    value={effectivePageIndex}
                    options={[
                        ...getIntroScreenPageOptions(survey),
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
            </LemonField.Pure>
        </div>
    ) : (
        <div className="flex flex-col">
            <h4 className="text-center">API survey response</h4>
            <SurveyAPIEditor survey={survey} />
        </div>
    )
}
