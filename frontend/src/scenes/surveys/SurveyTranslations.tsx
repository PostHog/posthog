import { useActions, useValues } from 'kea'
import type { KeyboardEvent } from 'react'

import { IconSparkles, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInputSelect, LemonTag } from '@posthog/lemon-ui'

import { COUNTRY_CODE_TO_LONG_NAME, LANGUAGE_CODE_TO_NAME } from 'lib/utils/geography/country'

import { MultipleSurveyQuestion, SurveyQuestion, SurveyQuestionType } from '~/types'

import { surveyLogic } from './surveyLogic'

export const COMMON_SURVEY_LANGUAGE_CODES = [
    'en',
    'en-US',
    'en-GB',
    'es',
    'es-ES',
    'es-MX',
    'fr',
    'fr-FR',
    'fr-CA',
    'de',
    'de-DE',
    'ar',
    'bg',
    'bn',
    'ca',
    'cs',
    'da',
    'el',
    'et',
    'fa',
    'fi',
    'he',
    'hi',
    'hr',
    'hu',
    'id',
    'it',
    'ja',
    'ko',
    'lt',
    'lv',
    'ms',
    'nl',
    'no',
    'pl',
    'pt',
    'pt-BR',
    'pt-PT',
    'ro',
    'ro-RO',
    'ru',
    'sk',
    'sl',
    'sr',
    'sv',
    'th',
    'tr',
    'uk',
    'ur',
    'vi',
    'zh',
    'zh-CN',
    'zh-TW',
]

const REGION_DISPLAY_NAME_OVERRIDES: Record<string, string> = {
    CN: 'Simplified',
    GB: 'UK',
    TW: 'Traditional',
    US: 'US',
}

export function getSurveyLanguageLabel(languageCode: string): string {
    const hyphenIndex = languageCode.indexOf('-')
    if (hyphenIndex === -1) {
        const languageName = LANGUAGE_CODE_TO_NAME[languageCode] ?? languageCode
        return `${languageName} (${languageCode})`
    }
    const baseLanguageCode = languageCode.substring(0, hyphenIndex)
    const regionCode = languageCode.substring(hyphenIndex + 1)

    const languageName = LANGUAGE_CODE_TO_NAME[baseLanguageCode] ?? baseLanguageCode

    if (!regionCode) {
        return `${languageName} (${languageCode})`
    }

    const normalizedRegionCode = regionCode.toUpperCase()
    const regionName =
        REGION_DISPLAY_NAME_OVERRIDES[normalizedRegionCode] ??
        COUNTRY_CODE_TO_LONG_NAME[normalizedRegionCode] ??
        regionCode

    return `${languageName} - ${regionName} (${languageCode})`
}

export const COMMON_LANGUAGES = COMMON_SURVEY_LANGUAGE_CODES.map((languageCode) => ({
    value: languageCode,
    label: getSurveyLanguageLabel(languageCode),
}))

const isChoiceQuestion = (question: SurveyQuestion): question is MultipleSurveyQuestion =>
    question.type === SurveyQuestionType.SingleChoice || question.type === SurveyQuestionType.MultipleChoice

export function SurveyTranslations(): JSX.Element {
    const {
        survey,
        editingLanguage,
        aiGeneratedTranslationFields,
        generatingTranslationDrafts,
        dataProcessingAccepted,
    } = useValues(surveyLogic)
    const { setSurveyValue, setEditingLanguage, generateTranslationDrafts } = useActions(surveyLogic)

    const surveyTranslations = survey.translations ?? {}
    const addedLanguages = Object.keys(surveyTranslations)
    const getLanguageLabel = (lang: string): string =>
        COMMON_LANGUAGES.find((language) => language.value === lang)?.label || getSurveyLanguageLabel(lang)
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
        <div className="flex flex-col gap-3 rounded border border-border bg-bg-light p-3">
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
                <LemonButton
                    type="secondary"
                    icon={<IconSparkles />}
                    loading={generatingTranslationDrafts}
                    disabledReason={
                        !editingLanguage
                            ? 'Add or select a language before generating translations'
                            : survey.id === 'new'
                              ? 'Save the survey before generating translations'
                              : !dataProcessingAccepted
                                ? 'AI data processing must be approved to generate translations'
                                : undefined
                    }
                    onClick={() => editingLanguage && generateTranslationDrafts(editingLanguage)}
                >
                    Fill with AI
                </LemonButton>
            </div>

            <div className="flex flex-wrap gap-2">
                {addedLanguages.length > 0 && (
                    <div
                        role="button"
                        tabIndex={0}
                        className={`flex items-center justify-between gap-2 px-2 py-1.5 border rounded cursor-pointer ${editingLanguage === null ? 'border-warning bg-warning-highlight' : 'border-border bg-bg-light'}`}
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
                        className={`flex items-center justify-between gap-2 px-2 py-1 border rounded cursor-pointer ${editingLanguage === lang ? 'border-warning bg-warning-highlight' : 'border-border bg-bg-light'}`}
                        onClick={() => selectLanguage(lang)}
                        onKeyDown={(event) => onLanguageKeyDown(event, lang)}
                    >
                        <div className="flex items-center gap-2">
                            <span>{getLanguageLabel(lang)}</span>
                            {aiGeneratedTranslationFields.some((path) => path.includes(`.${lang}.`)) && (
                                <LemonTag type="highlight">AI draft</LemonTag>
                            )}
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
