import { useActions, useValues } from 'kea'

import { LemonInput, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { SurveyQuestion } from '~/types'

import { defaultSurveyAppearance } from './constants'
import { isChoiceQuestion, isLinkQuestion, isRatingQuestion } from './questionTypeGuards'
import { surveyLogic } from './surveyLogic'

type QuestionTranslation = NonNullable<SurveyQuestion['translations']>[string]

function GuidedTranslationInput({
    label,
    value,
    source,
    onChange,
    multiline = false,
    aiGenerated = false,
}: {
    label: string
    value: string
    source?: string | null
    onChange: (value: string) => void
    multiline?: boolean
    aiGenerated?: boolean
}): JSX.Element {
    const labelWithState = aiGenerated ? (
        <span className="flex items-center gap-1">
            <span>{label}</span>
            <LemonTag type="highlight">AI draft</LemonTag>
        </span>
    ) : (
        label
    )
    const aiGeneratedClassName = aiGenerated
        ? 'border border-dashed border-accent bg-accent-highlight-secondary'
        : undefined

    return (
        <LemonField.Pure label={labelWithState} className="gap-1">
            {multiline ? (
                <LemonTextArea
                    value={value}
                    onChange={onChange}
                    placeholder={source || undefined}
                    minRows={2}
                    className={aiGeneratedClassName}
                />
            ) : (
                <LemonInput
                    value={value}
                    onChange={onChange}
                    placeholder={source || undefined}
                    fullWidth
                    className={aiGeneratedClassName}
                />
            )}
        </LemonField.Pure>
    )
}

/**
 * Per-field translation inputs (questions, buttons, confirmation) for a single language.
 * Shared by the wizard's Translations step and the hosted survey editor, which provide
 * their own language-management chrome around it.
 */
export function SurveyTranslationFields({ activeLanguage }: { activeLanguage: string }): JSX.Element {
    const { survey, aiGeneratedTranslationFields } = useValues(surveyLogic)
    const { setSurveyValue, clearAiGeneratedTranslationField } = useActions(surveyLogic)

    const translations = survey.translations ?? {}
    const appearance = { ...defaultSurveyAppearance, ...survey.appearance }

    const updateSurveyTranslation = (updates: Partial<NonNullable<(typeof survey)['translations']>[string]>): void => {
        for (const field of Object.keys(updates)) {
            clearAiGeneratedTranslationField(`translations.${activeLanguage}.${field}`)
        }
        setSurveyValue('translations', {
            ...translations,
            [activeLanguage]: { ...translations[activeLanguage], ...updates },
        })
    }

    const updateQuestionTranslation = (questionIndex: number, updates: Partial<QuestionTranslation>): void => {
        for (const field of Object.keys(updates)) {
            clearAiGeneratedTranslationField(`questions.${questionIndex}.translations.${activeLanguage}.${field}`)
        }
        setSurveyValue(
            'questions',
            survey.questions.map((question, index) => {
                if (index !== questionIndex) {
                    return question
                }
                const questionTranslations = question.translations ?? {}
                return {
                    ...question,
                    translations: {
                        ...questionTranslations,
                        [activeLanguage]: { ...question.translations?.[activeLanguage], ...updates },
                    },
                }
            })
        )
    }

    const updateChoiceTranslation = (questionIndex: number, choiceIndex: number, value: string): void => {
        const question = survey.questions[questionIndex]
        if (!isChoiceQuestion(question)) {
            return
        }
        const translatedChoices = [...(question.translations?.[activeLanguage]?.choices || question.choices || [])]
        translatedChoices[choiceIndex] = value
        clearAiGeneratedTranslationField(
            `questions.${questionIndex}.translations.${activeLanguage}.choices.${choiceIndex}`
        )
        updateQuestionTranslation(questionIndex, { choices: translatedChoices })
    }

    const isGeneratedSurveyField = (field: string): boolean =>
        aiGeneratedTranslationFields.includes(`translations.${activeLanguage}.${field}`)

    const isGeneratedQuestionField = (questionIndex: number, field: string): boolean =>
        aiGeneratedTranslationFields.includes(`questions.${questionIndex}.translations.${activeLanguage}.${field}`)

    const isGeneratedChoiceField = (questionIndex: number, choiceIndex: number): boolean =>
        aiGeneratedTranslationFields.includes(
            `questions.${questionIndex}.translations.${activeLanguage}.choices.${choiceIndex}`
        )

    return (
        <div className="space-y-6">
            {survey.questions.map((question, questionIndex) => {
                const questionTranslation = question.translations?.[activeLanguage] ?? {}
                const ratingQuestion = isRatingQuestion(question) ? question : null
                const linkQuestion = isLinkQuestion(question) ? question : null

                return (
                    <section key={questionIndex} className="space-y-3">
                        <h4 className="m-0 text-xs font-semibold uppercase tracking-wide text-muted">
                            Question {questionIndex + 1}
                        </h4>
                        <GuidedTranslationInput
                            label="Question"
                            value={questionTranslation.question || ''}
                            source={question.question}
                            aiGenerated={isGeneratedQuestionField(questionIndex, 'question')}
                            onChange={(questionText) =>
                                updateQuestionTranslation(questionIndex, { question: questionText })
                            }
                        />
                        {question.description ? (
                            <GuidedTranslationInput
                                label="Description"
                                value={questionTranslation.description || ''}
                                source={question.description}
                                aiGenerated={isGeneratedQuestionField(questionIndex, 'description')}
                                onChange={(description) => updateQuestionTranslation(questionIndex, { description })}
                                multiline
                            />
                        ) : null}
                        <GuidedTranslationInput
                            label="Button text"
                            value={questionTranslation.buttonText || ''}
                            source={
                                question.buttonText ||
                                (linkQuestion ? 'Continue' : appearance.submitButtonText || 'Submit')
                            }
                            aiGenerated={isGeneratedQuestionField(questionIndex, 'buttonText')}
                            onChange={(buttonText) => updateQuestionTranslation(questionIndex, { buttonText })}
                        />
                        {ratingQuestion ? (
                            <div className="grid gap-3 sm:grid-cols-2">
                                <GuidedTranslationInput
                                    label="Lower label"
                                    value={questionTranslation.lowerBoundLabel || ''}
                                    source={ratingQuestion.lowerBoundLabel}
                                    aiGenerated={isGeneratedQuestionField(questionIndex, 'lowerBoundLabel')}
                                    onChange={(lowerBoundLabel) =>
                                        updateQuestionTranslation(questionIndex, { lowerBoundLabel })
                                    }
                                />
                                <GuidedTranslationInput
                                    label="Upper label"
                                    value={questionTranslation.upperBoundLabel || ''}
                                    source={ratingQuestion.upperBoundLabel}
                                    aiGenerated={isGeneratedQuestionField(questionIndex, 'upperBoundLabel')}
                                    onChange={(upperBoundLabel) =>
                                        updateQuestionTranslation(questionIndex, { upperBoundLabel })
                                    }
                                />
                            </div>
                        ) : null}
                        {isChoiceQuestion(question) ? (
                            <div className="grid gap-2 sm:grid-cols-2">
                                {question.choices.map((choice, choiceIndex) => (
                                    <GuidedTranslationInput
                                        key={choiceIndex}
                                        label={`Choice ${choiceIndex + 1}`}
                                        value={questionTranslation.choices?.[choiceIndex] || ''}
                                        source={choice}
                                        aiGenerated={isGeneratedChoiceField(questionIndex, choiceIndex)}
                                        onChange={(value) => updateChoiceTranslation(questionIndex, choiceIndex, value)}
                                    />
                                ))}
                            </div>
                        ) : null}
                        {linkQuestion ? (
                            <GuidedTranslationInput
                                label="Link URL"
                                value={questionTranslation.link || ''}
                                source={linkQuestion.link}
                                aiGenerated={isGeneratedQuestionField(questionIndex, 'link')}
                                onChange={(link) => updateQuestionTranslation(questionIndex, { link })}
                            />
                        ) : null}
                    </section>
                )
            })}

            {appearance.displayThankYouMessage ? (
                <section className="space-y-3">
                    <h4 className="m-0 text-xs font-semibold uppercase tracking-wide text-muted">
                        Confirmation screen
                    </h4>
                    <GuidedTranslationInput
                        label="Header"
                        value={translations[activeLanguage]?.thankYouMessageHeader || ''}
                        source={appearance.thankYouMessageHeader}
                        aiGenerated={isGeneratedSurveyField('thankYouMessageHeader')}
                        onChange={(thankYouMessageHeader) => updateSurveyTranslation({ thankYouMessageHeader })}
                    />
                    {appearance.thankYouMessageDescription ? (
                        <GuidedTranslationInput
                            label="Description"
                            value={translations[activeLanguage]?.thankYouMessageDescription || ''}
                            source={appearance.thankYouMessageDescription}
                            aiGenerated={isGeneratedSurveyField('thankYouMessageDescription')}
                            onChange={(thankYouMessageDescription) =>
                                updateSurveyTranslation({ thankYouMessageDescription })
                            }
                            multiline
                        />
                    ) : null}
                    {appearance.thankYouMessageCloseButtonText ? (
                        <GuidedTranslationInput
                            label="Close button"
                            value={translations[activeLanguage]?.thankYouMessageCloseButtonText || ''}
                            source={appearance.thankYouMessageCloseButtonText}
                            aiGenerated={isGeneratedSurveyField('thankYouMessageCloseButtonText')}
                            onChange={(thankYouMessageCloseButtonText) =>
                                updateSurveyTranslation({ thankYouMessageCloseButtonText })
                            }
                        />
                    ) : null}
                </section>
            ) : null}
        </div>
    )
}
