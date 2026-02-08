import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { LemonInput } from 'lib/lemon-ui/LemonInput'

import { ProductTourSurveyQuestion, ProductTourSurveyQuestionType } from '~/types'

import { DEFAULT_OPEN_QUESTION, DEFAULT_RATING_QUESTION, getDefaultSurveyContent } from '../stepUtils'

export interface SurveyStepEditorProps {
    survey: ProductTourSurveyQuestion | undefined
    onChange: (survey: ProductTourSurveyQuestion) => void
}

export function SurveyStepEditor({ survey, onChange }: SurveyStepEditorProps): JSX.Element {
    const currentSurvey = survey ?? getDefaultSurveyContent('open')

    const updateSurvey = (updates: Partial<ProductTourSurveyQuestion>): void => {
        onChange({ ...currentSurvey, ...updates })
    }

    const handleTypeChange = (newType: ProductTourSurveyQuestionType): void => {
        if (newType === currentSurvey.type) {
            return
        }

        // When switching types, check if we should update the question text
        const isDefaultQuestion =
            currentSurvey.questionText === DEFAULT_OPEN_QUESTION ||
            currentSurvey.questionText === DEFAULT_RATING_QUESTION

        const newQuestionText = isDefaultQuestion
            ? newType === 'rating'
                ? DEFAULT_RATING_QUESTION
                : DEFAULT_OPEN_QUESTION
            : currentSurvey.questionText

        if (newType === 'rating') {
            onChange({
                type: 'rating',
                questionText: newQuestionText,
                display: 'emoji',
                scale: 5,
                lowerBoundLabel: currentSurvey.lowerBoundLabel ?? 'Not at all',
                upperBoundLabel: currentSurvey.upperBoundLabel ?? 'Very much',
            })
        } else {
            onChange({
                type: 'open',
                questionText: newQuestionText,
            })
        }
    }

    const handleDisplayChange = (display: 'emoji' | 'number'): void => {
        // Adjust scale if needed for new display type
        let scale = currentSurvey.scale ?? 5
        if (display === 'emoji' && scale === 10) {
            scale = 5
        } else if (display === 'number' && scale === 3) {
            scale = 5
        }
        updateSurvey({ display, scale })
    }

    return (
        <div className="space-y-3">
            {/* Question type toggle */}
            <LemonSegmentedButton
                size="small"
                fullWidth
                value={currentSurvey.type}
                onChange={(value) => handleTypeChange(value as ProductTourSurveyQuestionType)}
                options={[
                    { value: 'open', label: 'Open text' },
                    { value: 'rating', label: 'Rating' },
                ]}
            />

            {/* Question text */}
            <div className="space-y-1">
                <label className="text-xs font-medium">Question</label>
                <LemonInput
                    value={currentSurvey.questionText}
                    onChange={(value) => updateSurvey({ questionText: value })}
                    placeholder={currentSurvey.type === 'rating' ? DEFAULT_RATING_QUESTION : DEFAULT_OPEN_QUESTION}
                    size="small"
                    fullWidth
                />
            </div>

            {/* Rating-specific options */}
            {currentSurvey.type === 'rating' && (
                <div className="space-y-2">
                    <div className="flex gap-3 items-center">
                        <div className="flex gap-1.5 items-center">
                            <span className="text-xs text-muted">Type:</span>
                            <LemonSegmentedButton
                                size="xsmall"
                                value={currentSurvey.display ?? 'emoji'}
                                onChange={(value) => handleDisplayChange(value as 'emoji' | 'number')}
                                options={[
                                    { value: 'emoji', label: 'Emoji' },
                                    { value: 'number', label: 'Number' },
                                ]}
                            />
                        </div>
                        <div className="flex gap-1.5 items-center">
                            <span className="text-xs text-muted">Scale:</span>
                            <LemonSegmentedButton
                                size="xsmall"
                                value={currentSurvey.scale ?? 5}
                                onChange={(value) => updateSurvey({ scale: value as 3 | 5 | 10 })}
                                options={
                                    currentSurvey.display === 'number'
                                        ? [
                                              { value: 5, label: '1-5' },
                                              { value: 10, label: '0-10' },
                                          ]
                                        : [
                                              { value: 3, label: '1-3' },
                                              { value: 5, label: '1-5' },
                                          ]
                                }
                            />
                        </div>
                    </div>
                    <div className="flex gap-2">
                        <div className="flex-1 space-y-1">
                            <label className="text-xs text-muted">Low label</label>
                            <LemonInput
                                size="small"
                                value={currentSurvey.lowerBoundLabel ?? ''}
                                onChange={(value) => updateSurvey({ lowerBoundLabel: value })}
                                placeholder="Not at all"
                            />
                        </div>
                        <div className="flex-1 space-y-1">
                            <label className="text-xs text-muted">High label</label>
                            <LemonInput
                                size="small"
                                value={currentSurvey.upperBoundLabel ?? ''}
                                onChange={(value) => updateSurvey({ upperBoundLabel: value })}
                                placeholder="Very much"
                            />
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}
