import { useActions, useValues } from 'kea'
import type { KeyboardEvent } from 'react'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInputSelect } from '@posthog/lemon-ui'

import { MultipleSurveyQuestion, SurveyQuestion, SurveyQuestionType } from '~/types'

import { surveyLogic } from './surveyLogic'

export const COMMON_LANGUAGES = [
    { value: 'en', label: 'English (en)' },
    { value: 'en-US', label: 'English - US (en-US)' },
    { value: 'en-GB', label: 'English - UK (en-GB)' },
    { value: 'es', label: 'Spanish (es)' },
    { value: 'es-ES', label: 'Spanish - Spain (es-ES)' },
    { value: 'es-MX', label: 'Spanish - Mexico (es-MX)' },
    { value: 'fr', label: 'French (fr)' },
    { value: 'fr-FR', label: 'French - France (fr-FR)' },
    { value: 'fr-CA', label: 'French - Canada (fr-CA)' },
    { value: 'de', label: 'German (de)' },
    { value: 'de-DE', label: 'German - Germany (de-DE)' },
    { value: 'pt', label: 'Portuguese (pt)' },
    { value: 'pt-BR', label: 'Portuguese - Brazil (pt-BR)' },
    { value: 'pt-PT', label: 'Portuguese - Portugal (pt-PT)' },
    { value: 'zh', label: 'Chinese (zh)' },
    { value: 'zh-CN', label: 'Chinese - Simplified (zh-CN)' },
    { value: 'zh-TW', label: 'Chinese - Traditional (zh-TW)' },
    { value: 'ja', label: 'Japanese (ja)' },
    { value: 'ko', label: 'Korean (ko)' },
    { value: 'ru', label: 'Russian (ru)' },
    { value: 'ar', label: 'Arabic (ar)' },
    { value: 'hi', label: 'Hindi (hi)' },
    { value: 'it', label: 'Italian (it)' },
    { value: 'nl', label: 'Dutch (nl)' },
    { value: 'pl', label: 'Polish (pl)' },
    { value: 'tr', label: 'Turkish (tr)' },
]

const isChoiceQuestion = (question: SurveyQuestion): question is MultipleSurveyQuestion =>
    question.type === SurveyQuestionType.SingleChoice || question.type === SurveyQuestionType.MultipleChoice

export function SurveyTranslations(): JSX.Element {
    const { survey, editingLanguage } = useValues(surveyLogic)
    const { setSurveyValue, setEditingLanguage } = useActions(surveyLogic)

    const surveyTranslations = survey.translations ?? {}
    const addedLanguages = Object.keys(surveyTranslations)
    const getLanguageLabel = (lang: string): string => COMMON_LANGUAGES.find((l) => l.value === lang)?.label || lang
    const selectLanguage = (lang: string | null): void => setEditingLanguage(lang)
    const onLanguageKeyDown = (event: KeyboardEvent<HTMLDivElement>, lang: string | null): void => {
        if (event.currentTarget !== event.target) {
            return
        }
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault()
            selectLanguage(lang)
        }
    }

    const addLanguage = (lang: string): void => {
        if (!lang) {
            return
        }
        const currentTranslations = surveyTranslations
        if (currentTranslations[lang]) {
            return
        }

        // Initialize each question's translation with all translatable fields from defaults
        const updatedQuestions = survey.questions.map((question) => {
            const questionTranslations = question.translations ?? {}
            const baseTranslation = {
                question: question.question || '',
                description: question.description || '',
                buttonText: question.buttonText || '',
            }

            const newTranslation = {
                ...baseTranslation,
                ...(question.type === SurveyQuestionType.Rating
                    ? {
                          lowerBoundLabel: question.lowerBoundLabel || '',
                          upperBoundLabel: question.upperBoundLabel || '',
                      }
                    : {}),
                ...(isChoiceQuestion(question) ? { choices: question.choices || [] } : {}),
                ...(question.type === SurveyQuestionType.Link ? { link: question.link || '' } : {}),
            }

            return {
                ...question,
                translations: {
                    ...questionTranslations,
                    [lang]: {
                        ...questionTranslations[lang],
                        ...newTranslation,
                    },
                },
            }
        })

        setSurveyValue('questions', updatedQuestions)
        setSurveyValue('translations', {
            ...currentTranslations,
            [lang]: {
                name: survey.name || '',
                thankYouMessageHeader: survey.appearance?.thankYouMessageHeader || '',
                thankYouMessageDescription: survey.appearance?.thankYouMessageDescription || '',
                thankYouMessageCloseButtonText: survey.appearance?.thankYouMessageCloseButtonText || '',
            },
        })
        setEditingLanguage(lang)
    }

    const removeLanguage = (lang: string): void => {
        // Remove survey-level translations
        const currentTranslations = { ...surveyTranslations }
        delete currentTranslations[lang]
        setSurveyValue('translations', currentTranslations)

        // Remove question-level translations
        const updatedQuestions = survey.questions.map((question) => {
            if (question.translations && question.translations[lang]) {
                const questionTranslations = { ...question.translations }
                delete questionTranslations[lang]
                return {
                    ...question,
                    translations: questionTranslations,
                }
            }
            return question
        })
        setSurveyValue('questions', updatedQuestions)

        if (editingLanguage === lang) {
            setEditingLanguage(null)
        }
    }

    return (
        <div className={`flex flex-col ${addedLanguages.length > 0 ? 'gap-4' : ''}`}>
            <div className="flex gap-2">
                <LemonInputSelect
                    mode="single"
                    options={COMMON_LANGUAGES.filter((l) => !addedLanguages.includes(l.value)).map((l) => ({
                        key: l.value,
                        label: l.label,
                    }))}
                    onChange={(values) => {
                        const lang = values[0]
                        if (lang) {
                            addLanguage(lang)
                        }
                    }}
                    placeholder="Add a language (e.g., 'fr', 'French', 'fr-CA')"
                    className="grow"
                    allowCustomValues
                    autoFocus={addedLanguages.length === 0}
                    value={[]}
                />
            </div>

            <div className="space-y-2">
                {addedLanguages.length > 0 && (
                    <div
                        role="button"
                        tabIndex={0}
                        className={`flex items-center justify-between px-2 py-1.5 border rounded cursor-pointer ${editingLanguage === null ? 'border-warning bg-warning-highlight' : 'border-border'}`}
                        onClick={() => selectLanguage(null)}
                        onKeyDown={(event) => onLanguageKeyDown(event, null)}
                    >
                        <span>Default (original)</span>
                    </div>
                )}

                {addedLanguages.map((lang) => (
                    <div
                        key={lang}
                        role="button"
                        tabIndex={0}
                        className={`flex items-center justify-between px-2 py-1 border rounded cursor-pointer ${editingLanguage === lang ? 'border-warning bg-warning-highlight' : 'border-border'}`}
                        onClick={() => selectLanguage(lang)}
                        onKeyDown={(event) => onLanguageKeyDown(event, lang)}
                    >
                        <div className="flex items-center gap-2">
                            <span>{getLanguageLabel(lang)}</span>
                        </div>
                        <LemonButton
                            icon={<IconTrash />}
                            status="danger"
                            size="xsmall"
                            aria-label={`Delete translation for ${getLanguageLabel(lang)}`}
                            title={`Delete translation for ${getLanguageLabel(lang)}`}
                            onClick={(e) => {
                                e.stopPropagation()
                                LemonDialog.open({
                                    title: 'Delete translation',
                                    description: (
                                        <p className="py-2">
                                            Are you sure you want to delete the translation for{' '}
                                            <strong>{getLanguageLabel(lang)}</strong>? All translated content for this
                                            language will be permanently lost.
                                        </p>
                                    ),
                                    primaryButton: {
                                        children: 'Delete',
                                        status: 'danger',
                                        onClick: () => removeLanguage(lang),
                                    },
                                    secondaryButton: {
                                        children: 'Cancel',
                                    },
                                })
                            }}
                        />
                    </div>
                ))}
            </div>
        </div>
    )
}
