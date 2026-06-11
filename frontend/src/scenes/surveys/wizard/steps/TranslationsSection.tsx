import { useActions, useValues } from 'kea'

import { IconSparkles, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInput, LemonInputSelect, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { SurveyQuestion } from '~/types'

import { BaseLanguagePicker } from '../../BaseLanguagePicker'
import { defaultSurveyAppearance } from '../../constants'
import { COMMON_LANGUAGES, getSurveyLanguageLabel, getSurveyLanguageName } from '../../language'
import { LegacyTranslationKeysPanel } from '../../LegacyTranslationKeysPanel'
import { isChoiceQuestion, isLinkQuestion, isRatingQuestion } from '../../questionTypeGuards'
import { surveyLogic } from '../../surveyLogic'
import { useSurveyTranslationsForm } from '../../useSurveyTranslationsForm'
import { WizardPanel, WizardSection } from '../WizardLayout'

type QuestionTranslation = NonNullable<SurveyQuestion['translations']>[string]

function getLanguageLabel(language: string): string {
    return (
        COMMON_LANGUAGES.find((commonLanguage) => commonLanguage.value === language)?.label ||
        getSurveyLanguageLabel(language)
    )
}

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

interface TranslationsSectionProps {
    editingLanguage: string | null
    setEditingLanguage: (language: string | null) => void
}

export function TranslationsSection({ editingLanguage, setEditingLanguage }: TranslationsSectionProps): JSX.Element {
    const { survey, generatingTranslationDrafts, dataProcessingAccepted, aiGeneratedTranslationFields } =
        useValues(surveyLogic)
    const { setSurveyValue, generateTranslationDrafts, clearAiGeneratedTranslationField } = useActions(surveyLogic)

    const {
        baseLanguage,
        addedLanguages,
        validKeys,
        invalidKeys,
        pickerOptions,
        pickerError,
        setBaseLanguage,
        addLanguage,
        removeLanguage,
    } = useSurveyTranslationsForm({ editingLanguage, setEditingLanguage })

    const translations = survey.translations ?? {}
    const activeLanguage = editingLanguage && translations[editingLanguage] ? editingLanguage : null
    const appearance = { ...defaultSurveyAppearance, ...survey.appearance }

    const updateSurveyTranslation = (updates: Partial<NonNullable<(typeof survey)['translations']>[string]>): void => {
        if (!activeLanguage) {
            return
        }

        for (const field of Object.keys(updates)) {
            clearAiGeneratedTranslationField(`translations.${activeLanguage}.${field}`)
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
        clearAiGeneratedTranslationField(
            `questions.${questionIndex}.translations.${activeLanguage}.choices.${choiceIndex}`
        )
        updateQuestionTranslation(questionIndex, { choices: translatedChoices })
    }

    const isGeneratedSurveyField = (field: string): boolean =>
        !!activeLanguage && aiGeneratedTranslationFields.includes(`translations.${activeLanguage}.${field}`)

    const isGeneratedQuestionField = (questionIndex: number, field: string): boolean =>
        !!activeLanguage &&
        aiGeneratedTranslationFields.includes(`questions.${questionIndex}.translations.${activeLanguage}.${field}`)

    const isGeneratedChoiceField = (questionIndex: number, choiceIndex: number): boolean =>
        !!activeLanguage &&
        aiGeneratedTranslationFields.includes(
            `questions.${questionIndex}.translations.${activeLanguage}.choices.${choiceIndex}`
        )

    const hasGeneratedFieldsForActiveLanguage =
        !!activeLanguage && aiGeneratedTranslationFields.some((path) => path.includes(`.${activeLanguage}.`))

    return (
        <WizardSection title="Translations">
            <WizardPanel className="space-y-4">
                <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                    <h4 className="m-0 text-sm font-semibold uppercase tracking-wide text-muted">Original language</h4>
                    <span className="text-sm">
                        Survey is written in <strong>{getSurveyLanguageName(baseLanguage)}</strong>{' '}
                        <span className="text-muted">({baseLanguage})</span>
                    </span>
                    <BaseLanguagePicker
                        baseLanguage={baseLanguage}
                        onChange={setBaseLanguage}
                        translatedLanguages={addedLanguages}
                    />
                </div>

                <div className="flex flex-col gap-1">
                    <LemonInputSelect
                        mode="single"
                        options={pickerOptions}
                        onChange={(values) => {
                            const language = values[0]
                            if (language) {
                                addLanguage(language)
                            }
                        }}
                        placeholder="Add a translation"
                        allowCustomValues
                        value={[]}
                        data-attr="survey-translation-add"
                    />
                    {pickerError && (
                        <span role="alert" className="text-danger text-xs">
                            {pickerError}
                        </span>
                    )}
                </div>

                <div className="flex flex-wrap gap-2">
                    <LemonButton
                        size="small"
                        type={activeLanguage === null ? 'primary' : 'secondary'}
                        onClick={() => setEditingLanguage(null)}
                    >
                        {getSurveyLanguageName(baseLanguage)} (original)
                    </LemonButton>
                    {validKeys.map((language) => (
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

                <LegacyTranslationKeysPanel languages={invalidKeys} onRemove={removeLanguage} />

                {activeLanguage ? (
                    <div className="space-y-4 border-t border-border pt-4">
                        <div className="flex items-center justify-between gap-3">
                            <div>
                                <h3 className="m-0 text-sm font-semibold">{getLanguageLabel(activeLanguage)}</h3>
                                <p className="m-0 text-xs text-secondary">The preview uses this language.</p>
                            </div>
                            <div className="flex items-center gap-2">
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    icon={<IconSparkles />}
                                    loading={generatingTranslationDrafts}
                                    disabledReason={
                                        survey.id === 'new'
                                            ? 'Save the survey before generating translations'
                                            : !dataProcessingAccepted
                                              ? 'AI data processing must be approved to generate translations'
                                              : undefined
                                    }
                                    onClick={() => generateTranslationDrafts(activeLanguage)}
                                >
                                    Translate with AI
                                </LemonButton>
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
                        </div>

                        {hasGeneratedFieldsForActiveLanguage ? (
                            <p className="m-0 text-xs text-muted">
                                <LemonTag type="highlight" size="small">
                                    AI draft
                                </LemonTag>{' '}
                                Highlighted fields are AI-generated — double-check them.
                            </p>
                        ) : null}

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
                                                aiGenerated={isGeneratedQuestionField(questionIndex, 'buttonText')}
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
                                                    aiGenerated={isGeneratedQuestionField(
                                                        questionIndex,
                                                        'lowerBoundLabel'
                                                    )}
                                                    onChange={(lowerBoundLabel) =>
                                                        updateQuestionTranslation(questionIndex, { lowerBoundLabel })
                                                    }
                                                />
                                                <GuidedTranslationInput
                                                    label="Upper label"
                                                    value={questionTranslation.upperBoundLabel || ''}
                                                    source={ratingQuestion.upperBoundLabel}
                                                    aiGenerated={isGeneratedQuestionField(
                                                        questionIndex,
                                                        'upperBoundLabel'
                                                    )}
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
                                        onChange={(thankYouMessageHeader) =>
                                            updateSurveyTranslation({ thankYouMessageHeader })
                                        }
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
                    </div>
                ) : null}
            </WizardPanel>
        </WizardSection>
    )
}
