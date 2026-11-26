import { DeepPartialMap, ValidationErrorType } from 'kea-forms'
import { ReactNode, useId } from 'react'

import {
    Checkbox,
    Field,
    FieldLabel,
    Heading,
    NumberFieldGroup,
    NumberFieldInput,
    NumberFieldRoot,
    Separator,
    Text,
} from '@posthog/quill'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { NewSurvey, SurveyTheme } from 'scenes/surveys/constants'
import { SurveyAppearanceModal } from 'scenes/surveys/survey-appearance/SurveyAppearanceModal'
import { SurveyBehaviorOptions } from 'scenes/surveys/survey-appearance/SurveyBehaviorOptions'
import { SurveyThemeSelector } from 'scenes/surveys/wizard/SurveyThemeSelector'

import { AvailableFeature, Survey, SurveyAppearance, SurveyType } from '~/types'

import { QuillSurveyColorsAppearance } from './QuillSurveyColorsAppearance'
import { QuillSurveyContainerAppearance } from './QuillSurveyContainerAppearance'

function QuillCustomizationSection({
    title,
    description,
    children,
}: {
    title: string
    description?: string
    children: ReactNode
}): JSX.Element {
    return (
        <section className="flex flex-col gap-2">
            <div className="flex flex-col gap-0.5">
                <Heading size="sm" render={<h3 className="m-0" />}>
                    {title}
                </Heading>
                {description ? (
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        {description}
                    </Text>
                ) : null}
            </div>
            {children}
        </section>
    )
}

export function QuillCustomization({
    survey,
    surveyAppearance,
    selectedThemeId,
    onSelectTheme,
    siteThemeCard,
    surveysStylingAvailable,
    hasRatingButtons,
    hasPlaceholderText,
    hasBranchingLogic,
    deleteBranchingLogic,
    onAppearanceChange,
    validationErrors,
    disabledReason,
    onWhiteLabelChange,
    onPopupDelayToggle,
    onPopupDelayChange,
}: {
    survey: Survey | NewSurvey
    surveyAppearance: SurveyAppearance
    selectedThemeId: string | null
    onSelectTheme: (theme: SurveyTheme) => void
    siteThemeCard: JSX.Element | null
    surveysStylingAvailable: boolean
    hasRatingButtons: boolean
    hasPlaceholderText: boolean
    hasBranchingLogic: boolean
    deleteBranchingLogic?: () => void
    onAppearanceChange: (appearance: Partial<SurveyAppearance>) => void
    validationErrors?: DeepPartialMap<SurveyAppearance, ValidationErrorType> | null
    disabledReason?: string
    onWhiteLabelChange: (checked: boolean) => void
    onPopupDelayToggle: (checked: boolean) => void
    onPopupDelayChange: (value: number | undefined) => void
}): JSX.Element {
    const whiteLabelId = useId()
    const popupDelayId = useId()

    return (
        <div className="flex flex-col gap-5">
            {!surveysStylingAvailable && (
                <PayGateMini feature={AvailableFeature.SURVEYS_STYLING} featureDetail="survey-customization">
                    <></>
                </PayGateMini>
            )}

            <QuillCustomizationSection
                title="Theme"
                description="Start with a preset, then fine-tune individual colors below."
            >
                <SurveyThemeSelector
                    selectedThemeId={selectedThemeId}
                    onSelectTheme={onSelectTheme}
                    disabled={!surveysStylingAvailable || !!disabledReason}
                    showHeader={false}
                    leadingCard={siteThemeCard}
                />
            </QuillCustomizationSection>

            <Separator />

            <QuillCustomizationSection title="Colors">
                <QuillSurveyColorsAppearance
                    appearance={surveyAppearance}
                    onAppearanceChange={onAppearanceChange}
                    validationErrors={validationErrors}
                    customizeRatingButtons={hasRatingButtons}
                    customizePlaceholderText={hasPlaceholderText}
                    disabledReason={disabledReason}
                />
            </QuillCustomizationSection>

            {survey.type !== SurveyType.ExternalSurvey && (
                <>
                    <Separator />
                    <QuillCustomizationSection
                        title="Layout"
                        description="Container, placement, and typography. Container settings only apply to web surveys. Position also applies on iOS and React Native, and font family on iOS, Android, and Flutter."
                    >
                        <QuillSurveyContainerAppearance
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
                    </QuillCustomizationSection>
                </>
            )}

            <Separator />

            <QuillCustomizationSection title="Behavior">
                <div className="flex flex-col gap-3">
                    <Field orientation="horizontal" className="w-fit">
                        <Checkbox
                            id={whiteLabelId}
                            checked={!!survey.appearance?.whiteLabel}
                            onCheckedChange={onWhiteLabelChange}
                            disabledReason={disabledReason}
                        />
                        <FieldLabel htmlFor={whiteLabelId}>Hide PostHog branding</FieldLabel>
                    </Field>
                    <Separator />
                    <SurveyBehaviorOptions
                        survey={survey}
                        onAppearanceChange={onAppearanceChange}
                        disabledReason={disabledReason}
                        hasBranchingLogic={hasBranchingLogic}
                        deleteBranchingLogic={deleteBranchingLogic}
                    />
                    {survey.type !== SurveyType.ExternalSurvey && (
                        <>
                            <Separator />
                            <Field orientation="horizontal" className="flex-wrap items-center gap-2">
                                <Checkbox
                                    id={popupDelayId}
                                    checked={!!survey.appearance?.surveyPopupDelaySeconds}
                                    onCheckedChange={onPopupDelayToggle}
                                    disabledReason={disabledReason}
                                />
                                <FieldLabel htmlFor={popupDelayId}>Delay survey popup by at least</FieldLabel>
                                <NumberFieldRoot
                                    className="w-20"
                                    value={survey.appearance?.surveyPopupDelaySeconds ?? null}
                                    onValueChange={(value) => onPopupDelayChange(value ?? undefined)}
                                    min={1}
                                    max={3600}
                                    disabledReason={disabledReason}
                                >
                                    <NumberFieldGroup>
                                        <NumberFieldInput
                                            aria-label="Survey popup delay in seconds"
                                            data-attr="survey-popup-delay-input"
                                        />
                                    </NumberFieldGroup>
                                </NumberFieldRoot>
                                <Text size="xs" render={<span />}>
                                    seconds once the display conditions are met.
                                </Text>
                            </Field>
                        </>
                    )}
                </div>
            </QuillCustomizationSection>
        </div>
    )
}
