import { useActions, useValues } from 'kea'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInputSelect } from '@posthog/lemon-ui'

import { SurveyQuestionType } from '~/types'

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

export function SurveyTranslations(): JSX.Element {
    const { survey, editingLanguage } = useValues(surveyLogic)
    const { setSurveyValue, setEditingLanguage } = useActions(surveyLogic)

    const addedLanguages = Object.keys(survey.translations || {})

    const addLanguage = (lang: string): void => {
        if (!lang) {
            return
        }
        const currentTranslations = survey.translations || {}
        if (currentTranslations[lang]) {
            return
        }

        // Initialize each question's translation with choices arrays for multiple choice questions
        const updatedQuestions = survey.questions.map((question) => {
            if (
                question.type === SurveyQuestionType.SingleChoice ||
                question.type === SurveyQuestionType.MultipleChoice
            ) {
                return {
                    ...question,
                    translations: {
                        ...question.translations,
                        [lang]: {
                            ...question.translations?.[lang],
                            choices: question.choices || [],
                        },
                    },
                }
            }
            return question
        })

        setSurveyValue('questions', updatedQuestions)
        setSurveyValue('translations', {
            ...currentTranslations,
            [lang]: {},
        })
        setEditingLanguage(lang)
    }

    const removeLanguage = (lang: string): void => {
        const currentTranslations = { ...survey.translations }
        delete currentTranslations[lang]
        setSurveyValue('translations', currentTranslations)
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
                        className={`flex items-center justify-between px-2 py-1.5 border rounded cursor-pointer ${editingLanguage === null ? 'border-warning bg-warning-highlight' : 'border-border'}`}
                        onClick={() => setEditingLanguage(null)}
                    >
                        <span>Default (Original)</span>
                    </div>
                )}

                {addedLanguages.map((lang) => (
                    <div
                        key={lang}
                        className={`flex items-center justify-between px-2 py-1 border rounded cursor-pointer ${editingLanguage === lang ? 'border-warning bg-warning-highlight' : 'border-border'}`}
                        onClick={() => setEditingLanguage(lang)}
                    >
                        <div className="flex items-center gap-2">
                            <span>{COMMON_LANGUAGES.find((l) => l.value === lang)?.label || lang}</span>
                        </div>
                        <LemonButton
                            icon={<IconTrash />}
                            status="danger"
                            size="xsmall"
                            onClick={(e) => {
                                e.stopPropagation()
                                LemonDialog.open({
                                    title: 'Delete translation',
                                    description: (
                                        <p className="py-2">
                                            Are you sure you want to delete the translation for{' '}
                                            <strong>
                                                {COMMON_LANGUAGES.find((l) => l.value === lang)?.label || lang}
                                            </strong>
                                            ? This action cannot be undone.
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
