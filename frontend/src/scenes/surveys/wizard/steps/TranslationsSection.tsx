import { useActions, useValues } from 'kea'

import { IconSparkles, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInputSelect, LemonTag } from '@posthog/lemon-ui'

import { BaseLanguagePicker } from '../../BaseLanguagePicker'
import { COMMON_LANGUAGES, getSurveyLanguageLabel, getSurveyLanguageName } from '../../language'
import { LegacyTranslationKeysPanel } from '../../LegacyTranslationKeysPanel'
import { surveyLogic } from '../../surveyLogic'
import { SurveyTranslationFields } from '../../SurveyTranslationFields'
import { useSurveyTranslationsForm } from '../../useSurveyTranslationsForm'
import { WizardPanel, WizardSection } from '../WizardLayout'

function getLanguageLabel(language: string): string {
    return (
        COMMON_LANGUAGES.find((commonLanguage) => commonLanguage.value === language)?.label ||
        getSurveyLanguageLabel(language)
    )
}

interface TranslationsSectionProps {
    editingLanguage: string | null
    setEditingLanguage: (language: string | null) => void
}

export function TranslationsSection({ editingLanguage, setEditingLanguage }: TranslationsSectionProps): JSX.Element {
    const { survey, generatingTranslationDrafts, dataProcessingAccepted, aiGeneratedTranslationFields } =
        useValues(surveyLogic)
    const { generateTranslationDrafts } = useActions(surveyLogic)

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

                        <SurveyTranslationFields activeLanguage={activeLanguage} />
                    </div>
                ) : null}
            </WizardPanel>
        </WizardSection>
    )
}
