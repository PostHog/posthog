import { LemonCheckbox, LemonDialog, LemonDivider, LemonInput } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { NewSurvey } from 'scenes/surveys/constants'

import { Survey, SurveyAppearance } from '~/types'

type SurveyTranslations = NonNullable<Survey['translations']>

interface SurveyBehaviorOptionsProps {
    survey: Survey | NewSurvey
    onAppearanceChange: (appearance: Partial<SurveyAppearance>) => void
    disabledReason?: string
    hasBranchingLogic?: boolean
    deleteBranchingLogic?: () => void
    /** When provided (i.e. inside the survey editor), enables inline per-language back button labels. */
    onTranslationsChange?: (translations: SurveyTranslations) => void
}

// Shared by the classic editor and the guided wizard so both expose the same behavior toggles.
export function SurveyBehaviorOptions({
    survey,
    onAppearanceChange,
    disabledReason,
    hasBranchingLogic,
    deleteBranchingLogic,
    onTranslationsChange,
}: SurveyBehaviorOptionsProps): JSX.Element {
    const translations: SurveyTranslations = survey.translations ?? {}
    const translatedLanguages = onTranslationsChange ? Object.keys(translations) : []

    const setBackButtonTranslation = (language: string, value: string): void => {
        onTranslationsChange?.({
            ...translations,
            [language]: { ...translations[language], backButtonText: value || undefined },
        })
    }

    return (
        <div className="flex flex-col gap-3">
            <LemonCheckbox
                disabledReason={disabledReason}
                label="Shuffle questions"
                onChange={(checked) => {
                    if (checked && hasBranchingLogic) {
                        onAppearanceChange({ shuffleQuestions: false })

                        LemonDialog.open({
                            title: 'Your survey has active branching logic',
                            description: (
                                <p className="py-2">
                                    Enabling this option will remove your branching logic. Are you sure you want to
                                    continue?
                                </p>
                            ),
                            primaryButton: {
                                children: 'Continue',
                                status: 'danger',
                                onClick: () => {
                                    deleteBranchingLogic?.()
                                    onAppearanceChange({ shuffleQuestions: true })
                                },
                            },
                            secondaryButton: {
                                children: 'Cancel',
                            },
                        })
                    } else {
                        onAppearanceChange({ shuffleQuestions: checked })
                    }
                }}
                checked={survey.appearance?.shuffleQuestions}
            />
            <LemonDivider className="my-0" />
            <LemonCheckbox
                disabledReason={disabledReason}
                label="Allow going back to previous questions"
                onChange={(checked) =>
                    onAppearanceChange({
                        allowGoBack: checked,
                        backButtonText: checked ? survey.appearance?.backButtonText : undefined,
                    })
                }
                checked={survey.appearance?.allowGoBack}
            />
            {survey.appearance?.allowGoBack && (
                <LemonField.Pure label="Back button text" className="ml-6">
                    <div className="flex max-w-xs flex-col gap-1">
                        <LemonInput
                            size="small"
                            placeholder="Back"
                            value={survey.appearance?.backButtonText ?? ''}
                            onChange={(backButtonText) => onAppearanceChange({ backButtonText })}
                            className="ignore-error-border"
                            disabledReason={disabledReason}
                        />
                        {translatedLanguages.map((language) => (
                            <LemonInput
                                key={language}
                                size="small"
                                prefix={<span className="text-xs font-medium uppercase text-muted">{language}</span>}
                                placeholder={survey.appearance?.backButtonText || 'Back'}
                                value={translations[language]?.backButtonText ?? ''}
                                onChange={(value) => setBackButtonTranslation(language, value)}
                                className="ignore-error-border"
                                disabledReason={disabledReason}
                            />
                        ))}
                    </div>
                </LemonField.Pure>
            )}
        </div>
    )
}
