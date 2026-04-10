import { useValues } from 'kea'
import type { ReactNode } from 'react'

import { LemonCheckbox, LemonDialog, LemonDivider, LemonInput } from '@posthog/lemon-ui'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { defaultSurveyAppearance, getMatchingSurveyThemeId } from 'scenes/surveys/constants'
import { SurveyAppearanceModal } from 'scenes/surveys/survey-appearance/SurveyAppearanceModal'
import {
    SurveyColorsAppearance,
    SurveyContainerAppearance,
} from 'scenes/surveys/survey-appearance/SurveyAppearanceSections'
import { CustomizationProps } from 'scenes/surveys/survey-appearance/types'
import { SurveyThemeSelector } from 'scenes/surveys/wizard/SurveyThemeSelector'

import { AvailableFeature, SurveyType } from '~/types'

import { surveysLogic } from '../surveysLogic'

function CustomizationSection({
    title,
    description,
    children,
}: {
    title: string
    description?: string
    children: ReactNode
}): JSX.Element {
    return (
        <section className="space-y-3">
            <div className="space-y-0.5">
                <h3 className="m-0 text-sm font-semibold">{title}</h3>
                {description ? <p className="m-0 text-xs text-secondary">{description}</p> : null}
            </div>
            {children}
        </section>
    )
}

export function Customization({
    survey,
    hasRatingButtons,
    hasPlaceholderText,
    hasBranchingLogic,
    onAppearanceChange,
    deleteBranchingLogic,
    validationErrors,
    disabledReason,
}: CustomizationProps): JSX.Element {
    const { surveysStylingAvailable } = useValues(surveysLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)

    const surveyAppearance = { ...defaultSurveyAppearance, ...survey.appearance }
    const selectedThemeId = getMatchingSurveyThemeId(survey.appearance)

    return (
        <div className="flex flex-col divide-y divide-border [&>*]:py-5 [&>*:first-child]:pt-0 [&>*:last-child]:pb-0">
            {!surveysStylingAvailable && (
                <PayGateMini feature={AvailableFeature.SURVEYS_STYLING}>
                    <></>
                </PayGateMini>
            )}

            <CustomizationSection
                title="Theme"
                description="Start with a preset, then fine-tune individual colors below."
            >
                <SurveyThemeSelector
                    selectedThemeId={selectedThemeId}
                    onSelectTheme={(theme) => onAppearanceChange(theme.appearance)}
                    disabled={!surveysStylingAvailable || !!disabledReason}
                    showHeader={false}
                />
            </CustomizationSection>

            <CustomizationSection title="Colors">
                <SurveyColorsAppearance
                    appearance={surveyAppearance}
                    onAppearanceChange={onAppearanceChange}
                    validationErrors={validationErrors}
                    customizeRatingButtons={hasRatingButtons}
                    customizePlaceholderText={hasPlaceholderText}
                    disabledReason={disabledReason}
                />
            </CustomizationSection>

            {survey.type !== SurveyType.ExternalSurvey && (
                <CustomizationSection
                    title="Layout"
                    description="Container, placement, and typography. Only applied in web surveys, not native mobile apps."
                >
                    <SurveyContainerAppearance
                        appearance={surveyAppearance}
                        onAppearanceChange={onAppearanceChange}
                        validationErrors={validationErrors}
                        surveyType={survey.type}
                        disabledReason={disabledReason}
                    />
                    <SurveyAppearanceModal
                        survey={survey}
                        onAppearanceChange={onAppearanceChange}
                        hasPlaceholderText={hasPlaceholderText}
                        hasRatingButtons={hasRatingButtons}
                        validationErrors={validationErrors}
                        disabledReason={disabledReason}
                    />
                </CustomizationSection>
            )}

            <CustomizationSection title="Behavior">
                <div className="flex flex-col gap-3">
                    <LemonCheckbox
                        label="Hide PostHog branding"
                        onChange={(checked) => {
                            if (checked) {
                                guardAvailableFeature(AvailableFeature.WHITE_LABELLING, () =>
                                    onAppearanceChange({ whiteLabel: checked })
                                )
                            } else {
                                onAppearanceChange({ whiteLabel: checked })
                            }
                        }}
                        checked={survey.appearance?.whiteLabel}
                        disabledReason={disabledReason}
                    />
                    <LemonDivider className="my-0" />
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
                                            Enabling this option will remove your branching logic. Are you sure you want
                                            to continue?
                                        </p>
                                    ),
                                    primaryButton: {
                                        children: 'Continue',
                                        status: 'danger',
                                        onClick: () => {
                                            if (deleteBranchingLogic) {
                                                deleteBranchingLogic()
                                            }
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
                </div>
                {survey.type !== SurveyType.ExternalSurvey && (
                    <>
                        <LemonDivider className="my-3" />
                        <LemonField.Pure>
                            <div className="flex flex-row items-center gap-2 font-medium">
                                <LemonCheckbox
                                    checked={!!survey.appearance?.surveyPopupDelaySeconds}
                                    onChange={(checked) => {
                                        const surveyPopupDelaySeconds = checked ? 5 : undefined
                                        onAppearanceChange({ surveyPopupDelaySeconds })
                                    }}
                                    disabledReason={disabledReason}
                                />
                                Delay survey popup by at least{' '}
                                <LemonInput
                                    type="number"
                                    data-attr="survey-popup-delay-input"
                                    size="small"
                                    min={1}
                                    max={3600}
                                    value={survey.appearance?.surveyPopupDelaySeconds || NaN}
                                    onChange={(newValue) => {
                                        if (newValue && newValue > 0) {
                                            onAppearanceChange({ surveyPopupDelaySeconds: newValue })
                                        } else {
                                            onAppearanceChange({
                                                surveyPopupDelaySeconds: undefined,
                                            })
                                        }
                                    }}
                                    className="w-12 ignore-error-border"
                                    disabledReason={disabledReason}
                                />{' '}
                                seconds once the display conditions are met.
                            </div>
                        </LemonField.Pure>
                    </>
                )}
            </CustomizationSection>
        </div>
    )
}
