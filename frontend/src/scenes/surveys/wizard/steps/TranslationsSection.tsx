import { useActions, useValues } from 'kea'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInput, LemonInputSelect, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import {
    LinkSurveyQuestion,
    MultipleSurveyQuestion,
    RatingSurveyQuestion,
    SurveyQuestion,
    SurveyQuestionType,
} from '~/types'

import { defaultSurveyAppearance } from '../../constants'
import { surveyLogic } from '../../surveyLogic'
import { COMMON_LANGUAGES } from '../../SurveyTranslations'
import { WizardPanel, WizardSection } from '../WizardLayout'

type QuestionTranslation = NonNullable<SurveyQuestion['translations']>[string]

function getLanguageLabel(language: string): string {
    return COMMON_LANGUAGES.find((commonLanguage) => commonLanguage.value === language)?.label || language
}

function isChoiceQuestion(question: SurveyQuestion): question is MultipleSurveyQuestion {
    return question.type === SurveyQuestionType.SingleChoice || question.type === SurveyQuestionType.MultipleChoice
}

function isRatingQuestion(question: SurveyQuestion): question is RatingSurveyQuestion {
    return question.type === SurveyQuestionType.Rating
}

function isLinkQuestion(question: SurveyQuestion): question is LinkSurveyQuestion {
    return question.type === SurveyQuestionType.Link
}

function GuidedTranslationInput({
    label,
    value,
    source,
    onChange,
    multiline = false,
}: {
    label: string
    value: string
    source?: string | null
    onChange: (value: string) => void
    multiline?: boolean
}): JSX.Element {
    return (
        <LemonField.Pure label={label} className="gap-1">
            {multiline ? (
                <LemonTextArea value={value} onChange={onChange} placeholder={source || undefined} minRows={2} />
            ) : (
                <LemonInput value={value} onChange={onChange} placeholder={source || undefined} fullWidth />
            )}
        </LemonField.Pure>
    )
}

interface TranslationsSectionProps {
    editingLanguage: string | null
    setEditingLanguage: (language: string | null) => void
}

export function TranslationsSection({ editingLanguage, setEditingLanguage }: TranslationsSectionProps): JSX.Element {
    const { survey } = useValues(surveyLogic)
    const { setSurveyValue } = useActions(surveyLogic)

    const translations = survey.translations ?? {}
    const addedLanguages = Object.keys(translations)
    const activeLanguage = editingLanguage && translations[editingLanguage] ? editingLanguage : null
    const appearance = { ...defaultSurveyAppearance, ...survey.appearance }

    const addLanguage = (language: string): void => {
        if (!language || translations[language]) {
            return
        }

        setSurveyValue('translations', {
            ...translations,
            [language]: {
                thankYouMessageHeader: appearance.thankYouMessageHeader || '',
                thankYouMessageDescription: appearance.thankYouMessageDescription || '',
                thankYouMessageCloseButtonText: appearance.thankYouMessageCloseButtonText || '',
            },
        })
        setSurveyValue(
            'questions',
            survey.questions.map((question) => {
                const questionTranslations = question.translations ?? {}

                return {
                    ...question,
                    translations: {
                        ...questionTranslations,
                        [language]: {
                            question: question.question || '',
                            description: question.description || '',
                            buttonText: question.buttonText || '',
                            ...(isChoiceQuestion(question) ? { choices: question.choices || [] } : {}),
                            ...(isRatingQuestion(question)
                                ? {
                                      lowerBoundLabel: question.lowerBoundLabel || '',
                                      upperBoundLabel: question.upperBoundLabel || '',
                                  }
                                : {}),
                            ...(isLinkQuestion(question) ? { link: question.link || '' } : {}),
                        },
                    },
                }
            })
        )
        setEditingLanguage(language)
    }

    const removeLanguage = (language: string): void => {
        const nextTranslations = { ...translations }
        delete nextTranslations[language]

        setSurveyValue('translations', nextTranslations)
        setSurveyValue(
            'questions',
            survey.questions.map((question) => {
                if (!question.translations?.[language]) {
                    return question
                }

                const nextQuestionTranslations = { ...question.translations }
                delete nextQuestionTranslations[language]

                return {
                    ...question,
                    translations: nextQuestionTranslations,
                }
            })
        )

        if (editingLanguage === language) {
            setEditingLanguage(null)
        }
    }

    const updateSurveyTranslation = (updates: Partial<NonNullable<(typeof survey)['translations']>[string]>): void => {
        if (!activeLanguage) {
            return
        }

        setSurveyValue('translations', {
            ...translations,
            [activeLanguage]: {
                ...translations[activeLanguage],
                ...updates,
            },
        })
    }

    const updateQuestionTranslation = (questionIndex: number, updates: Partial<QuestionTranslation>): void => {
        if (!activeLanguage) {
            return
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
                        [activeLanguage]: {
                            ...question.translations?.[activeLanguage],
                            ...updates,
                        },
                    },
                }
            })
        )
    }

    const updateChoiceTranslation = (questionIndex: number, choiceIndex: number, value: string): void => {
        const question = survey.questions[questionIndex]
        if (!activeLanguage || !isChoiceQuestion(question)) {
            return
        }

        const translatedChoices = [...(question.translations?.[activeLanguage]?.choices || question.choices || [])]
        translatedChoices[choiceIndex] = value
        updateQuestionTranslation(questionIndex, { choices: translatedChoices })
    }

    return (
        <WizardSection
            title="Translations"
            description="Translate the respondent-facing copy. Targeting, scheduling, and branching stay shared across languages."
            descriptionClassName="text-sm"
        >
            <WizardPanel className="space-y-4">
                <LemonInputSelect
                    mode="single"
                    options={COMMON_LANGUAGES.filter((language) => !addedLanguages.includes(language.value)).map(
                        (language) => ({
                            key: language.value,
                            label: language.label,
                        })
                    )}
                    onChange={(values) => {
                        const language = values[0]
                        if (language) {
                            addLanguage(language)
                        }
                    }}
                    placeholder="Add a language"
                    allowCustomValues
                    value={[]}
                />

                {addedLanguages.length > 0 ? (
                    <div className="flex flex-wrap gap-2">
                        <LemonButton
                            size="small"
                            type={activeLanguage === null ? 'primary' : 'secondary'}
                            onClick={() => setEditingLanguage(null)}
                        >
                            Original
                        </LemonButton>
                        {addedLanguages.map((language) => (
                            <LemonButton
                                key={language}
                                size="small"
                                type={activeLanguage === language ? 'primary' : 'secondary'}
                                onClick={() => setEditingLanguage(language)}
                            >
                                {getLanguageLabel(language)}
                            </LemonButton>
                        ))}
                    </div>
                ) : null}

                {activeLanguage ? (
                    <div className="space-y-4 border-t border-border pt-4">
                        <div className="flex items-center justify-between gap-3">
                            <div>
                                <h3 className="m-0 text-sm font-semibold">{getLanguageLabel(activeLanguage)}</h3>
                                <p className="m-0 text-xs text-secondary">The preview uses this language.</p>
                            </div>
                            <LemonButton
                                icon={<IconTrash />}
                                type="tertiary"
                                status="danger"
                                size="small"
                                onClick={() => {
                                    LemonDialog.open({
                                        title: 'Delete translation',
                                        description: (
                                            <p className="py-2">
                                                Delete the translation for{' '}
                                                <strong>{getLanguageLabel(activeLanguage)}</strong>?
                                            </p>
                                        ),
                                        primaryButton: {
                                            children: 'Delete',
                                            status: 'danger',
                                            onClick: () => removeLanguage(activeLanguage),
                                        },
                                        secondaryButton: {
                                            children: 'Cancel',
                                        },
                                    })
                                }}
                            >
                                Delete
                            </LemonButton>
                        </div>

                        <div className="space-y-3">
                            {survey.questions.map((question, questionIndex) => {
                                const questionTranslation = question.translations?.[activeLanguage] ?? {}
                                const ratingQuestion = isRatingQuestion(question) ? question : null
                                const linkQuestion = isLinkQuestion(question) ? question : null

                                return (
                                    <div
                                        key={questionIndex}
                                        className="space-y-3 rounded-lg border border-border bg-bg-light p-3"
                                    >
                                        <div className="text-xs font-semibold text-secondary">
                                            Question {questionIndex + 1}
                                        </div>
                                        <GuidedTranslationInput
                                            label="Question"
                                            value={questionTranslation.question || ''}
                                            source={question.question}
                                            onChange={(questionText) =>
                                                updateQuestionTranslation(questionIndex, { question: questionText })
                                            }
                                        />
                                        {question.description ? (
                                            <GuidedTranslationInput
                                                label="Description"
                                                value={questionTranslation.description || ''}
                                                source={question.description}
                                                onChange={(description) =>
                                                    updateQuestionTranslation(questionIndex, { description })
                                                }
                                                multiline
                                            />
                                        ) : null}
                                        {question.buttonText ? (
                                            <GuidedTranslationInput
                                                label="Button text"
                                                value={questionTranslation.buttonText || ''}
                                                source={question.buttonText}
                                                onChange={(buttonText) =>
                                                    updateQuestionTranslation(questionIndex, { buttonText })
                                                }
                                            />
                                        ) : null}
                                        {ratingQuestion ? (
                                            <div className="grid gap-3 sm:grid-cols-2">
                                                <GuidedTranslationInput
                                                    label="Lower label"
                                                    value={questionTranslation.lowerBoundLabel || ''}
                                                    source={ratingQuestion.lowerBoundLabel}
                                                    onChange={(lowerBoundLabel) =>
                                                        updateQuestionTranslation(questionIndex, { lowerBoundLabel })
                                                    }
                                                />
                                                <GuidedTranslationInput
                                                    label="Upper label"
                                                    value={questionTranslation.upperBoundLabel || ''}
                                                    source={ratingQuestion.upperBoundLabel}
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
                                                        onChange={(value) =>
                                                            updateChoiceTranslation(questionIndex, choiceIndex, value)
                                                        }
                                                    />
                                                ))}
                                            </div>
                                        ) : null}
                                        {linkQuestion ? (
                                            <GuidedTranslationInput
                                                label="Link URL"
                                                value={questionTranslation.link || ''}
                                                source={linkQuestion.link}
                                                onChange={(link) => updateQuestionTranslation(questionIndex, { link })}
                                            />
                                        ) : null}
                                    </div>
                                )
                            })}
                        </div>

                        {appearance.displayThankYouMessage ? (
                            <div className="space-y-3 rounded-lg border border-border bg-bg-light p-3">
                                <div className="text-xs font-semibold text-secondary">Confirmation screen</div>
                                <GuidedTranslationInput
                                    label="Header"
                                    value={translations[activeLanguage]?.thankYouMessageHeader || ''}
                                    source={appearance.thankYouMessageHeader}
                                    onChange={(thankYouMessageHeader) =>
                                        updateSurveyTranslation({ thankYouMessageHeader })
                                    }
                                />
                                {appearance.thankYouMessageDescription ? (
                                    <GuidedTranslationInput
                                        label="Description"
                                        value={translations[activeLanguage]?.thankYouMessageDescription || ''}
                                        source={appearance.thankYouMessageDescription}
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
                                        onChange={(thankYouMessageCloseButtonText) =>
                                            updateSurveyTranslation({ thankYouMessageCloseButtonText })
                                        }
                                    />
                                ) : null}
                            </div>
                        ) : null}
                    </div>
                ) : null}
            </WizardPanel>
        </WizardSection>
    )
}
