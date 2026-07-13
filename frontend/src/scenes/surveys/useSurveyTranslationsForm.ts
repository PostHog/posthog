import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import {
    COMMON_LANGUAGES,
    classifyTranslationKeys,
    describeInvalidLanguageCode,
    getBaseLanguage,
    normalizeLanguageCode,
} from './language'
import { isChoiceQuestion, isLinkQuestion, isRatingQuestion } from './questionTypeGuards'
import { surveyLogic } from './surveyLogic'

interface UseSurveyTranslationsFormArgs {
    editingLanguage: string | null
    setEditingLanguage: (language: string | null) => void
}

interface PickerOption {
    key: string
    label: string
}

interface UseSurveyTranslationsFormReturn {
    baseLanguage: string
    addedLanguages: string[]
    validKeys: string[]
    invalidKeys: string[]
    pickerOptions: PickerOption[]
    pickerError: string | null
    setPickerError: (error: string | null) => void
    setBaseLanguage: (next: string) => void
    addLanguage: (rawLanguage: string) => void
    removeLanguage: (language: string) => void
}

export function useSurveyTranslationsForm({
    editingLanguage,
    setEditingLanguage,
}: UseSurveyTranslationsFormArgs): UseSurveyTranslationsFormReturn {
    const { survey } = useValues(surveyLogic)
    const { setSurveyValue } = useActions(surveyLogic)

    const baseLanguage = getBaseLanguage(survey)
    const surveyTranslations = survey.translations ?? {}
    const addedLanguages = Object.keys(surveyTranslations)
    const [pickerError, setPickerError] = useState<string | null>(null)

    const { invalidKeys, validKeys } = useMemo(
        () => classifyTranslationKeys(addedLanguages, baseLanguage),
        [addedLanguages, baseLanguage]
    )

    const normalizedBase = useMemo(() => normalizeLanguageCode(baseLanguage), [baseLanguage])
    const normalizedAdded = useMemo(() => new Set(addedLanguages.map(normalizeLanguageCode)), [addedLanguages])

    const pickerOptions = useMemo<PickerOption[]>(
        () =>
            COMMON_LANGUAGES.filter((language) => {
                const normalized = normalizeLanguageCode(language.value)
                return normalized !== normalizedBase && !normalizedAdded.has(normalized)
            }).map((language) => ({ key: language.value, label: language.label })),
        [normalizedBase, normalizedAdded]
    )

    const setBaseLanguage = (next: string): void => {
        setSurveyValue('base_language', next)
        if (editingLanguage && normalizeLanguageCode(editingLanguage) === next) {
            setEditingLanguage(null)
        }
    }

    const addLanguage = (rawLanguage: string): void => {
        const error = describeInvalidLanguageCode(rawLanguage, baseLanguage)
        if (error) {
            setPickerError(error)
            return
        }
        const language = normalizeLanguageCode(rawLanguage)
        setPickerError(null)
        if (normalizedAdded.has(language)) {
            return
        }

        const updatedQuestions = survey.questions.map((question) => {
            const questionTranslations = question.translations ?? {}
            const newTranslation = {
                question: question.question || '',
                description: question.description || '',
                buttonText: question.buttonText || '',
                ...(isRatingQuestion(question)
                    ? {
                          lowerBoundLabel: question.lowerBoundLabel || '',
                          upperBoundLabel: question.upperBoundLabel || '',
                      }
                    : {}),
                ...(isChoiceQuestion(question) ? { choices: question.choices || [] } : {}),
                ...(isLinkQuestion(question) ? { link: question.link || '' } : {}),
            }

            return {
                ...question,
                translations: {
                    ...questionTranslations,
                    [language]: {
                        ...questionTranslations[language],
                        ...newTranslation,
                    },
                },
            }
        })

        setSurveyValue('questions', updatedQuestions)
        setSurveyValue('translations', {
            ...surveyTranslations,
            [language]: {
                name: survey.name || '',
                thankYouMessageHeader: survey.appearance?.thankYouMessageHeader || '',
                thankYouMessageDescription: survey.appearance?.thankYouMessageDescription || '',
                thankYouMessageCloseButtonText: survey.appearance?.thankYouMessageCloseButtonText || '',
            },
        })
        setEditingLanguage(language)
    }

    const removeLanguage = (language: string): void => {
        const nextTranslations = { ...surveyTranslations }
        delete nextTranslations[language]
        setSurveyValue('translations', nextTranslations)

        const updatedQuestions = survey.questions.map((question) => {
            if (!question.translations?.[language]) {
                return question
            }
            const nextQuestionTranslations = { ...question.translations }
            delete nextQuestionTranslations[language]
            return { ...question, translations: nextQuestionTranslations }
        })
        setSurveyValue('questions', updatedQuestions)

        if (editingLanguage === language) {
            setEditingLanguage(null)
        }
    }

    return {
        baseLanguage,
        addedLanguages,
        validKeys,
        invalidKeys,
        pickerOptions,
        pickerError,
        setPickerError,
        setBaseLanguage,
        addLanguage,
        removeLanguage,
    }
}
