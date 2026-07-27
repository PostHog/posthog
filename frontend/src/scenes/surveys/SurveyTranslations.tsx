import { useActions, useValues } from 'kea'

import { IconSparkles, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInputSelect, LemonTag } from '@posthog/lemon-ui'

import { BaseLanguagePicker } from './BaseLanguagePicker'
import {
    COMMON_LANGUAGES,
    DEFAULT_SURVEY_BASE_LANGUAGE,
    getSurveyLanguageLabel,
    getSurveyLanguageName,
} from './language'
import { LegacyTranslationKeysPanel } from './LegacyTranslationKeysPanel'
import { surveyLogic } from './surveyLogic'
import { useSurveyTranslationsForm } from './useSurveyTranslationsForm'

export function SurveyTranslations(): JSX.Element {
    const {
        survey,
        editingLanguage,
        aiGeneratedTranslationFields,
        generatingTranslationDrafts,
        dataProcessingAccepted,
    } = useValues(surveyLogic)
    const { setEditingLanguage, generateTranslationDrafts } = useActions(surveyLogic)

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

    const getLanguageLabel = (lang: string): string =>
        COMMON_LANGUAGES.find((language) => language.value === lang)?.label || getSurveyLanguageLabel(lang)
    const selectLanguage = (lang: string | null): void => setEditingLanguage(lang)

    return (
        <div className="flex flex-col gap-3">
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
                            value={[]}
                            data-attr="survey-translation-add"
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
                        {getSurveyLanguageName(baseLanguage)} (original)
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

                <LegacyTranslationKeysPanel languages={invalidKeys} onRemove={removeLanguage} />
            </div>

            {baseLanguage !== DEFAULT_SURVEY_BASE_LANGUAGE && (
                <p className="text-xs text-muted m-0">
                    The SDK shows the original text whenever a user's locale doesn't have a translation.
                </p>
            )}
        </div>
    )
}
