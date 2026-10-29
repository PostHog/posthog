import { useActions, useValues } from 'kea'

import { LemonBanner, LemonInput, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { INTRO_SCREEN_DEFAULT_BUTTON_TEXT, INTRO_SCREEN_TEXT_FIELDS } from './constants'
import { HTMLEditor } from './SurveyAppearanceUtils'
import { getIntroScreenDescriptionContentType, isIntroScreenShown } from './surveyIntroScreen'
import { surveyLogic } from './surveyLogic'

type IntroScreenTextField = (typeof INTRO_SCREEN_TEXT_FIELDS)[number]

type IntroScreenInputProps = {
    value: string
    onChange: (value: string) => void
    placeholder: string
    className: string
}

const PLACEHOLDERS: Record<IntroScreenTextField, string> = {
    introScreenHeader: 'ex: Help us improve',
    introScreenDescription: 'ex: This takes less than a minute.',
    introScreenButtonText: INTRO_SCREEN_DEFAULT_BUTTON_TEXT,
}

export function SurveyEditIntroScreenContent({
    activeEditingLanguage,
}: {
    activeEditingLanguage: string | null
}): JSX.Element {
    const { survey, translationErrorsForField, aiGeneratedTranslationFields } = useValues(surveyLogic)
    const { setSurveyValue, clearAiGeneratedTranslationField } = useActions(surveyLogic)

    const isAiGenerated = (field: IntroScreenTextField): boolean =>
        !!activeEditingLanguage &&
        aiGeneratedTranslationFields.includes(`translations.${activeEditingLanguage}.${field}`)

    const setValue = (field: IntroScreenTextField, value: string): void => {
        if (activeEditingLanguage) {
            clearAiGeneratedTranslationField(`translations.${activeEditingLanguage}.${field}`)
            setSurveyValue('translations', {
                ...survey.translations,
                [activeEditingLanguage]: { ...survey.translations?.[activeEditingLanguage], [field]: value },
            })
        } else {
            setSurveyValue('appearance', { ...survey.appearance, [field]: value })
        }
    }

    const renderField = (
        field: IntroScreenTextField,
        label: string,
        renderInput: (props: IntroScreenInputProps) => JSX.Element,
        className?: string
    ): JSX.Element => {
        const error = translationErrorsForField(-1, field)
        return (
            <LemonField.Pure
                label={
                    isAiGenerated(field) ? (
                        <span className="flex items-center gap-1">
                            <span>{label}</span>
                            <LemonTag type="highlight">AI draft</LemonTag>
                        </span>
                    ) : (
                        label
                    )
                }
                className={className}
            >
                <Tooltip title={error?.error ?? ''} placement="top">
                    {renderInput({
                        value:
                            (activeEditingLanguage
                                ? survey.translations?.[activeEditingLanguage]?.[field]
                                : survey.appearance?.[field]) ?? '',
                        onChange: (value) => setValue(field, value),
                        placeholder: activeEditingLanguage ? (survey.appearance?.[field] ?? '') : PLACEHOLDERS[field],
                        className: [
                            error ? 'border border-warning hover:border-primary' : '',
                            isAiGenerated(field)
                                ? 'border border-dashed border-accent bg-accent-highlight-secondary'
                                : '',
                        ]
                            .filter(Boolean)
                            .join(' '),
                    })}
                </Tooltip>
            </LemonField.Pure>
        )
    }

    return (
        <>
            {!isIntroScreenShown(survey.appearance) && (
                <LemonBanner type="warning" className="mb-2">
                    The intro screen won't show until it has a header or a description.
                </LemonBanner>
            )}
            <p className="text-secondary text-xs mb-2">
                The survey counts as shown while the intro is on screen, so response rates include people who never
                start the questions.
            </p>
            {renderField('introScreenHeader', 'Intro header', (props) => (
                <LemonInput {...props} />
            ))}
            {renderField(
                'introScreenDescription',
                'Intro description',
                ({ placeholder, ...props }) => (
                    <HTMLEditor
                        {...props}
                        textPlaceholder={placeholder}
                        activeTab={getIntroScreenDescriptionContentType(survey.appearance)}
                        onTabChange={(key) =>
                            setSurveyValue('appearance', {
                                ...survey.appearance,
                                introScreenDescriptionContentType: key === 'html' ? 'html' : 'text',
                            })
                        }
                        disableTabSwitching={!!activeEditingLanguage}
                    />
                ),
                'mt-3'
            )}
            {renderField(
                'introScreenButtonText',
                'Button text',
                (props) => (
                    <LemonInput {...props} />
                ),
                'mt-2'
            )}
        </>
    )
}
