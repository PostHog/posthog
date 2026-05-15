import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconSparkles, IconTrash, IconWarning } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInputSelect, LemonTag } from '@posthog/lemon-ui'

import { MultipleSurveyQuestion, SurveyQuestion, SurveyQuestionType } from '~/types'

import { BaseLanguagePicker } from './BaseLanguagePicker'
import {
    COMMON_LANGUAGES,
    DEFAULT_SURVEY_BASE_LANGUAGE,
    classifyTranslationKeys,
    describeInvalidLanguageCode,
    getBaseLanguage,
    getSurveyLanguageLabel,
    getSurveyLanguageName,
    normalizeLanguageCode,
} from './language'
import { surveyLogic } from './surveyLogic'

// Re-exports kept so older imports continue to work — prefer importing from `./language` directly.
export { COMMON_LANGUAGES, COMMON_SURVEY_LANGUAGE_CODES, getSurveyLanguageLabel } from './language'

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

    const baseLanguage = getBaseLanguage(survey)
    const surveyTranslations = survey.translations ?? {}
    const addedLanguages = Object.keys(surveyTranslations)
    const [pickerError, setPickerError] = useState<string | null>(null)

    const { invalidKeys, validKeys } = useMemo(
        () => classifyTranslationKeys(addedLanguages, baseLanguage),
        [addedLanguages, baseLanguage]
    )

    const getLanguageLabel = (lang: string): string =>
        COMMON_LANGUAGES.find((language) => language.value === lang)?.label || getSurveyLanguageLabel(lang)
    const selectLanguage = (lang: string | null): void => setEditingLanguage(lang)

    const setBaseLanguage = (next: string): void => {
        setSurveyValue('base_language', next)
        // If the user was editing the same language they just set as the base, clear it.
        if (editingLanguage && normalizeLanguageCode(editingLanguage) === next) {
            setEditingLanguage(null)
        }
    }

    const addLanguage = (rawLang: string): void => {
        const error = describeInvalidLanguageCode(rawLang, baseLanguage)
        if (error) {
            setPickerError(error)
            return
        }
        const lang = normalizeLanguageCode(rawLang)
        setPickerError(null)
        const currentTranslations = surveyTranslations
        if (currentTranslations[lang]) {
            return
        }

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
        const currentTranslations = { ...surveyTranslations }
        delete currentTranslations[lang]
        setSurveyValue('translations', currentTranslations)

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

    const pickerOptions = COMMON_LANGUAGES.filter(
        (l) => l.value !== baseLanguage && !addedLanguages.includes(l.value)
    ).map((l) => ({ key: l.value, label: l.label }))

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <h4 className="m-0 text-sm font-semibold uppercase tracking-wide text-muted">Original language</h4>
                <span className="text-sm">
                    Survey is written in <strong>{getSurveyLanguageName(baseLanguage)}</strong>{' '}
                    <span className="text-muted">({baseLanguage})</span>
                </span>
                <BaseLanguagePicker baseLanguage={baseLanguage} onChange={setBaseLanguage} />
            </div>

            <div className="flex flex-col gap-2">
                <h4 className="m-0 text-sm font-semibold uppercase tracking-wide text-muted">Translations</h4>
                <div className="flex gap-2">
                    <div className="grow flex flex-col gap-1">
                        <LemonInputSelect
                            mode="single"
                            options={pickerOptions}
                            onChange={(values) => {
                                const lang = values[0]
                                if (lang) {
                                    addLanguage(lang)
                                }
                            }}
                            placeholder="Add a translation (e.g. 'fr', 'French', 'fr-CA')"
                            allowCustomValues
                            autoFocus={validKeys.length === 0}
                            value={[]}
                        />
                        {pickerError && (
                            <span role="alert" className="text-danger text-xs">
                                {pickerError}
                            </span>
                        )}
                    </div>
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
                        Translate with AI
                    </LemonButton>
                </div>

                <div className="flex flex-wrap gap-2">
                    <LemonButton
                        size="small"
                        type={editingLanguage === null ? 'primary' : 'secondary'}
                        onClick={() => selectLanguage(null)}
                    >
                        {getSurveyLanguageName(baseLanguage)} <span className="text-muted ml-1">(original)</span>
                    </LemonButton>

                    {validKeys.map((lang) => {
                        const aiDraft = aiGeneratedTranslationFields.some((path) => path.includes(`.${lang}.`))
                        return (
                            <LemonButton
                                key={lang}
                                size="small"
                                type={editingLanguage === lang ? 'primary' : 'secondary'}
                                onClick={() => selectLanguage(lang)}
                                sideIcon={
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
                                                        Delete the translation for{' '}
                                                        <strong>{getLanguageLabel(lang)}</strong>? All translated
                                                        content for this language will be permanently lost.
                                                    </p>
                                                ),
                                                primaryButton: {
                                                    children: 'Delete',
                                                    status: 'danger',
                                                    onClick: () => removeLanguage(lang),
                                                },
                                                secondaryButton: { children: 'Cancel' },
                                            })
                                        }}
                                    />
                                }
                            >
                                <span className="flex items-center gap-2">
                                    {getLanguageLabel(lang)}
                                    {aiDraft && (
                                        <LemonTag type="highlight" size="small">
                                            AI draft
                                        </LemonTag>
                                    )}
                                </span>
                            </LemonButton>
                        )
                    })}
                </div>

                {invalidKeys.length > 0 && (
                    <div className="flex flex-col gap-1 text-sm">
                        <div className="flex items-center gap-2 text-warning font-semibold">
                            <IconWarning />
                            Legacy translation keys
                        </div>
                        <p className="m-0 text-xs text-muted">
                            These codes the SDK can't match. Remove or re-add with a valid BCP-47 code (e.g. 'en',
                            'es-MX').
                        </p>
                        <div className="flex flex-wrap gap-2 mt-1">
                            {invalidKeys.map((lang) => (
                                <div
                                    key={lang}
                                    className="flex items-center gap-1 rounded border border-border px-2 py-0.5"
                                >
                                    <code className="text-xs">{lang}</code>
                                    <LemonButton
                                        icon={<IconTrash />}
                                        status="danger"
                                        size="xsmall"
                                        aria-label={`Remove legacy translation '${lang}'`}
                                        onClick={() =>
                                            LemonDialog.open({
                                                title: 'Remove legacy translation',
                                                description: (
                                                    <p className="py-2">
                                                        Remove the translation stored under <code>{lang}</code>? It
                                                        currently has no effect at runtime — the SDK never matches this
                                                        code.
                                                    </p>
                                                ),
                                                primaryButton: {
                                                    children: 'Remove',
                                                    status: 'danger',
                                                    onClick: () => removeLanguage(lang),
                                                },
                                                secondaryButton: { children: 'Cancel' },
                                            })
                                        }
                                    />
                                </div>
                            ))}
                        </div>
                    </div>
                )}
            </div>

            {baseLanguage !== DEFAULT_SURVEY_BASE_LANGUAGE && (
                <p className="text-xs text-muted m-0">
                    The SDK shows the original text whenever a user's locale doesn't have a translation.
                </p>
            )}
        </div>
    )
}
