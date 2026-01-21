import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { getNextSurveyStep } from 'posthog-js/dist/surveys-preview'
import { useState } from 'react'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import {
    AvailableFeature,
    SurveyAppearance,
    SurveyPosition,
    SurveyQuestionBranchingType,
    SurveyQuestionType,
} from '~/types'

import { SurveyAppearancePreview } from '../../SurveyAppearancePreview'
import { NewSurvey, SurveyTheme, WEB_SAFE_FONTS, defaultSurveyAppearance, surveyThemes } from '../../constants'
import { surveyLogic } from '../../surveyLogic'
import { surveysLogic } from '../../surveysLogic'
import { ColorInput } from '../ColorInput'
import { SurveyThemeSelector } from '../SurveyThemeSelector'

export function AppearanceStep(): JSX.Element {
    const { survey } = useValues(surveyLogic)
    const { setSurveyValue } = useActions(surveyLogic)
    const { surveysStylingAvailable } = useValues(surveysLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const { isDarkModeOn } = useValues(themeLogic)

    const [previewPageIndex, setPreviewPageIndex] = useState(0)
    const [previewBackground, setPreviewBackground] = useState<'light' | 'dark'>(() =>
        isDarkModeOn ? 'dark' : 'light'
    )
    const [selectedThemeId, setSelectedThemeId] = useState<string | null>(() => {
        const currentAppearance = survey.appearance
        if (!currentAppearance) {
            return 'clean'
        }
        const matchingTheme = surveyThemes.find(
            (theme) =>
                theme.appearance.backgroundColor === currentAppearance.backgroundColor &&
                theme.appearance.submitButtonColor === currentAppearance.submitButtonColor
        )
        return matchingTheme?.id || null
    })

    const appearance: SurveyAppearance = { ...defaultSurveyAppearance, ...survey.appearance }
    const hasRatingButtons = survey.questions?.some((q) => q.type === SurveyQuestionType.Rating)

    const onAppearanceChange = (updates: Partial<SurveyAppearance>): void => {
        setSurveyValue('appearance', { ...appearance, ...updates })
    }

    const onManualColorChange = (updates: Partial<SurveyAppearance>): void => {
        setSelectedThemeId(null)
        onAppearanceChange(updates)
    }

    const handleThemeSelect = (theme: SurveyTheme): void => {
        setSelectedThemeId(theme.id)
        onAppearanceChange(theme.appearance)
    }

    const previewSurvey: NewSurvey = {
        ...survey,
        id: 'new',
    } as NewSurvey

    const totalPreviewPages = survey.questions.length + (appearance.displayThankYouMessage ? 1 : 0)

    return (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Left: Controls */}
            <div className="lg:col-span-2 space-y-4">
                <div>
                    <h2 className="text-xl font-semibold mb-1">How should it look?</h2>
                    <p className="text-secondary text-sm">
                        Customize colors and styling. You can use CSS variables (e.g. var(--brand-color)) for dynamic
                        theming.
                    </p>
                </div>

                {/* Paywall */}
                {!surveysStylingAvailable && (
                    <PayGateMini feature={AvailableFeature.SURVEYS_STYLING}>
                        <></>
                    </PayGateMini>
                )}

                {/* Theme selector */}
                <SurveyThemeSelector
                    selectedThemeId={selectedThemeId}
                    onSelectTheme={handleThemeSelect}
                    disabled={!surveysStylingAvailable}
                />

                {/* Color customization */}
                <div className="space-y-2">
                    <h3 className="font-medium m-0 text-sm">Fine-tune colors</h3>
                    <div className="grid grid-cols-2 gap-x-4 gap-y-2">
                        <LemonField.Pure label="Background" className="gap-1">
                            <ColorInput
                                value={appearance.backgroundColor}
                                onChange={(backgroundColor) => onManualColorChange({ backgroundColor })}
                                disabled={!surveysStylingAvailable}
                            />
                        </LemonField.Pure>
                        <LemonField.Pure label="Border" className="gap-1">
                            <ColorInput
                                value={appearance.borderColor}
                                onChange={(borderColor) => onManualColorChange({ borderColor })}
                                disabled={!surveysStylingAvailable}
                            />
                        </LemonField.Pure>
                        <LemonField.Pure label="Submit button" className="gap-1">
                            <ColorInput
                                value={appearance.submitButtonColor}
                                onChange={(submitButtonColor) => onManualColorChange({ submitButtonColor })}
                                disabled={!surveysStylingAvailable}
                            />
                        </LemonField.Pure>
                        <LemonField.Pure label="Question text" className="gap-1">
                            <ColorInput
                                value={appearance.textColor}
                                onChange={(textColor) => onManualColorChange({ textColor })}
                                disabled={!surveysStylingAvailable}
                            />
                        </LemonField.Pure>
                        {hasRatingButtons && (
                            <>
                                <LemonField.Pure label="Rating buttons" className="gap-1">
                                    <ColorInput
                                        value={appearance.ratingButtonColor}
                                        onChange={(ratingButtonColor) =>
                                            onManualColorChange({
                                                ratingButtonColor,
                                                inputBackground: ratingButtonColor,
                                            })
                                        }
                                        disabled={!surveysStylingAvailable}
                                    />
                                </LemonField.Pure>
                                <LemonField.Pure label="Selected rating" className="gap-1">
                                    <ColorInput
                                        value={appearance.ratingButtonActiveColor}
                                        onChange={(ratingButtonActiveColor) =>
                                            onManualColorChange({ ratingButtonActiveColor })
                                        }
                                        disabled={!surveysStylingAvailable}
                                    />
                                </LemonField.Pure>
                            </>
                        )}
                    </div>
                </div>

                {/* Branding */}
                <LemonCheckbox
                    label="Hide PostHog branding"
                    checked={appearance.whiteLabel}
                    onChange={(checked) => {
                        if (checked) {
                            guardAvailableFeature(AvailableFeature.WHITE_LABELLING, () =>
                                onAppearanceChange({ whiteLabel: checked })
                            )
                        } else {
                            onAppearanceChange({ whiteLabel: checked })
                        }
                    }}
                />

                {/* Advanced options */}
                <LemonCollapse
                    panels={[
                        {
                            key: 'advanced',
                            header: 'Advanced options',
                            className: 'p-2',
                            content: (
                                <div className="space-y-4">
                                    <div className="grid grid-cols-2 gap-x-4 gap-y-2">
                                        <LemonField.Pure label="Position" className="gap-1">
                                            <LemonSelect
                                                value={appearance.position}
                                                onChange={(position) => onAppearanceChange({ position })}
                                                options={[
                                                    { label: 'Bottom right', value: SurveyPosition.Right },
                                                    { label: 'Bottom left', value: SurveyPosition.Left },
                                                    { label: 'Bottom center', value: SurveyPosition.Center },
                                                    { label: 'Top right', value: SurveyPosition.TopRight },
                                                    { label: 'Top left', value: SurveyPosition.TopLeft },
                                                    { label: 'Top center', value: SurveyPosition.TopCenter },
                                                    { label: 'Middle right', value: SurveyPosition.MiddleRight },
                                                    { label: 'Middle left', value: SurveyPosition.MiddleLeft },
                                                    { label: 'Middle center', value: SurveyPosition.MiddleCenter },
                                                ]}
                                                fullWidth
                                                disabled={!surveysStylingAvailable}
                                            />
                                        </LemonField.Pure>
                                        <LemonField.Pure label="Font family" className="gap-1">
                                            <LemonSelect
                                                value={appearance.fontFamily}
                                                onChange={(fontFamily) => onAppearanceChange({ fontFamily })}
                                                options={WEB_SAFE_FONTS.map((font) => ({
                                                    label: font.label,
                                                    value: font.value,
                                                }))}
                                                fullWidth
                                                disabled={!surveysStylingAvailable}
                                            />
                                        </LemonField.Pure>
                                        <LemonField.Pure label="Survey width" className="gap-1">
                                            <LemonInput
                                                value={appearance.maxWidth}
                                                onChange={(maxWidth) => onAppearanceChange({ maxWidth })}
                                                placeholder="300px"
                                                disabled={!surveysStylingAvailable}
                                            />
                                        </LemonField.Pure>
                                        <LemonField.Pure label="Border radius" className="gap-1">
                                            <LemonInput
                                                value={appearance.borderRadius}
                                                onChange={(borderRadius) => onAppearanceChange({ borderRadius })}
                                                placeholder="10px"
                                                disabled={!surveysStylingAvailable}
                                            />
                                        </LemonField.Pure>
                                    </div>
                                </div>
                            ),
                        },
                    ]}
                    size="small"
                    embedded
                />
            </div>

            {/* Right: Preview */}
            <div className="lg:sticky lg:top-8 lg:self-start">
                <div className="space-y-3">
                    <div className="flex items-center justify-between">
                        <h3 className="font-medium m-0 text-sm">Preview</h3>
                        <LemonSwitch
                            checked={previewBackground === 'dark'}
                            onChange={(checked) => setPreviewBackground(checked ? 'dark' : 'light')}
                            label={previewBackground === 'dark' ? 'Dark page' : 'Light page'}
                        />
                    </div>

                    <div
                        className={clsx(
                            'border border-border rounded-lg flex items-center justify-center relative min-h-[400px] p-4',
                            previewBackground === 'light' ? 'bg-white' : 'bg-[#1d1f27]'
                        )}
                    >
                        <SurveyAppearancePreview
                            survey={previewSurvey}
                            previewPageIndex={previewPageIndex}
                            onPreviewSubmit={(response) => {
                                const next = getNextSurveyStep(previewSurvey, previewPageIndex, response)
                                if (next === SurveyQuestionBranchingType.End && !appearance.displayThankYouMessage) {
                                    return
                                }
                                setPreviewPageIndex(
                                    next === SurveyQuestionBranchingType.End ? survey.questions.length : next
                                )
                            }}
                        />
                    </div>

                    {/* Preview navigation */}
                    {totalPreviewPages > 1 && (
                        <div className="flex items-center justify-center gap-2">
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconChevronLeft />}
                                onClick={() => setPreviewPageIndex(Math.max(0, previewPageIndex - 1))}
                                disabledReason={previewPageIndex === 0 ? 'First question' : undefined}
                            />
                            <span className="text-muted text-sm min-w-[80px] text-center">
                                {previewPageIndex < survey.questions.length
                                    ? `${previewPageIndex + 1} of ${survey.questions.length}`
                                    : 'Thank you'}
                            </span>
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconChevronRight />}
                                onClick={() =>
                                    setPreviewPageIndex(Math.min(totalPreviewPages - 1, previewPageIndex + 1))
                                }
                                disabledReason={previewPageIndex >= totalPreviewPages - 1 ? 'Last screen' : undefined}
                            />
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}
