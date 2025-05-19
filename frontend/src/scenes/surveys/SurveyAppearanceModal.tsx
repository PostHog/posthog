import { IconCheck } from '@posthog/icons'
import {
    LemonButton,
    LemonCheckbox,
    LemonDivider,
    LemonInput,
    LemonModal,
    LemonSelect,
    LemonTabs,
} from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { getNextSurveyStep } from 'posthog-js/dist/surveys-preview'
import { useState } from 'react'

import {
    AvailableFeature,
    SurveyAppearance,
    SurveyPosition,
    SurveyQuestionBranchingType,
    SurveyQuestionType,
    SurveyType,
    SurveyWidgetType,
} from '~/types'

import { defaultSurveyAppearance, WEB_SAFE_FONTS } from './constants'
import { SurveyAppearancePreview } from './SurveyAppearancePreview'
import { surveyLogic } from './surveyLogic'
import { surveysLogic } from './surveysLogic'

const IGNORE_ERROR_BORDER_CLASS = 'ignore-error-border'

interface SurveyAppearanceModalProps {
    visible: boolean
    onClose: () => void
}

type PreviewScreenSize = 'mobile' | 'tablet' | 'desktop'

// Grid positions based on the enum
const gridPositions: SurveyPosition[] = [
    SurveyPosition.TopLeft,
    SurveyPosition.TopCenter,
    SurveyPosition.TopRight,
    SurveyPosition.MiddleLeft,
    SurveyPosition.MiddleCenter,
    SurveyPosition.MiddleRight,
    SurveyPosition.Left,
    SurveyPosition.Center,
    SurveyPosition.Right,
    // Bottom positions are not in the current enum, will add if they become available
    // SurveyPosition.BottomLeft, SurveyPosition.BottomCenter, SurveyPosition.BottomRight
]

const positionDisplayNames: Record<SurveyPosition, string> = {
    [SurveyPosition.TopLeft]: 'Top Left',
    [SurveyPosition.TopCenter]: 'Top Center',
    [SurveyPosition.TopRight]: 'Top Right',
    [SurveyPosition.MiddleLeft]: 'Middle Left',
    [SurveyPosition.MiddleCenter]: 'Middle Center',
    [SurveyPosition.MiddleRight]: 'Middle Right',
    // [SurveyPosition.BottomLeft]: 'Bottom Left',
    // [SurveyPosition.BottomCenter]: 'Bottom Center',
    // [SurveyPosition.BottomRight]: 'Bottom Right',
    [SurveyPosition.Left]: 'Bottom Left',
    [SurveyPosition.Center]: 'Bottom Center',
    [SurveyPosition.Right]: 'Bottom Right',
    [SurveyPosition.NextToTrigger]: 'Next to feedback button',
}

export function SurveyAppearanceModal({ visible, onClose }: SurveyAppearanceModalProps): JSX.Element | null {
    const { survey, surveyErrors, selectedPageIndex } = useValues(surveyLogic)
    const { setSurveyValue, setSelectedPageIndex } = useActions(surveyLogic)
    const { surveysStylingAvailable } = useValues(surveysLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)

    const [activeScreenSize, setActiveScreenSize] = useState<PreviewScreenSize>('desktop')

    const appearance: SurveyAppearance = { ...defaultSurveyAppearance, ...(survey.appearance || {}) }
    const validationErrors = surveyErrors?.appearance
    const surveyType = survey.type

    const onAppearanceChange = (newAppearance: Partial<SurveyAppearance>): void => {
        setSurveyValue('appearance', { ...appearance, ...newAppearance })
    }

    const customizeRatingButtons = survey.questions.some((question) => question.type === SurveyQuestionType.Rating)
    const customizePlaceholderText = survey.questions.some((question) => question.type === SurveyQuestionType.Open)

    const screenDimensions: Record<PreviewScreenSize, { width: string; height: string; scale?: number }> = {
        mobile: { width: '375px', height: '667px' },
        tablet: { width: '768px', height: '1024px' },
        desktop: { width: '100%', height: '100%' },
    }

    const currentDimensions = screenDimensions[activeScreenSize]

    if (survey.type === SurveyType.API) {
        return null
    }

    const surveyPositioningStyles: React.CSSProperties = {
        position: 'absolute',
    }

    return (
        <LemonModal isOpen={visible} onClose={onClose} fullScreen simple>
            <LemonModal.Header>Customize Survey Apperance</LemonModal.Header>
            <LemonModal.Content className="flex flex-row flex-1 h-full gap-4 overflow-hidden">
                <div className="flex-1 overflow-y-auto flex flex-col gap-2 pr-1">
                    {!surveysStylingAvailable && (
                        <PayGateMini feature={AvailableFeature.SURVEYS_STYLING} className="mb-4">
                            <></>
                        </PayGateMini>
                    )}

                    <div className="grid grid-cols-2 gap-1 items-start">
                        <h3 className="col-span-2 mb-0">Survey Container Options</h3>
                        <LemonField.Pure label="Max width" className="flex-1 gap-1">
                            <LemonInput
                                value={appearance.maxWidth}
                                onChange={(maxWidth) => onAppearanceChange({ maxWidth })}
                                disabled={!surveysStylingAvailable}
                                className={IGNORE_ERROR_BORDER_CLASS}
                            />
                        </LemonField.Pure>
                        <LemonField.Pure label="Background color" className="flex-1 gap-1">
                            <LemonInput
                                value={appearance.backgroundColor}
                                onChange={(backgroundColor) => onAppearanceChange({ backgroundColor })}
                                disabled={!surveysStylingAvailable}
                                className={clsx(
                                    validationErrors?.backgroundColor ? 'border-danger' : IGNORE_ERROR_BORDER_CLASS
                                )}
                            />
                            {validationErrors?.backgroundColor && (
                                <LemonField.Error error={validationErrors?.backgroundColor} />
                            )}
                        </LemonField.Pure>
                        <LemonField.Pure label="Border color" className="flex-1 gap-1">
                            <LemonInput
                                value={appearance.borderColor}
                                onChange={(borderColor) => onAppearanceChange({ borderColor })}
                                disabled={!surveysStylingAvailable}
                                className={clsx(
                                    validationErrors?.borderColor ? 'border-danger' : IGNORE_ERROR_BORDER_CLASS
                                )}
                            />
                            {validationErrors?.borderColor && (
                                <LemonField.Error error={validationErrors?.borderColor} />
                            )}
                        </LemonField.Pure>
                        <LemonField.Pure label="Box padding" className="flex-1 gap-1">
                            <LemonInput
                                value={appearance.boxPadding}
                                onChange={(boxPadding) => onAppearanceChange({ boxPadding })}
                                disabled={!surveysStylingAvailable}
                                className={clsx(
                                    validationErrors?.boxPadding ? 'border-danger' : IGNORE_ERROR_BORDER_CLASS
                                )}
                            />
                            {validationErrors?.boxPadding && <LemonField.Error error={validationErrors?.boxPadding} />}
                        </LemonField.Pure>
                        <LemonField.Pure label="Box shadow" className="flex-1 gap-1">
                            <LemonInput
                                value={appearance.boxShadow}
                                onChange={(boxShadow) => onAppearanceChange({ boxShadow })}
                            />
                        </LemonField.Pure>
                        <LemonField.Pure label="Border radius" className="flex-1 gap-1">
                            <LemonInput
                                value={appearance.borderRadius}
                                onChange={(borderRadius) => onAppearanceChange({ borderRadius })}
                                disabled={!surveysStylingAvailable}
                                className={clsx(
                                    validationErrors?.borderRadius ? 'border-danger' : IGNORE_ERROR_BORDER_CLASS
                                )}
                            />
                            {validationErrors?.borderRadius && (
                                <LemonField.Error error={validationErrors?.borderRadius} />
                            )}
                        </LemonField.Pure>

                        <LemonField.Pure
                            label="Position"
                            info={
                                surveyType === SurveyType.Widget && appearance.widgetType === SurveyWidgetType.Selector
                                    ? 'The "next to feedback button" option requires posthog.js version 1.235.2 or higher.'
                                    : undefined
                            }
                            className="gap-1 col-span-2"
                        >
                            <div className="grid grid-cols-3 gap-1 mb-1">
                                {gridPositions.map((position) => (
                                    <LemonButton
                                        key={position}
                                        type="tertiary"
                                        size="small"
                                        onClick={() => onAppearanceChange({ position })}
                                        active={appearance.position === position}
                                        disabled={!surveysStylingAvailable}
                                        className="justify-center text-xs" // Ensure text is centered and button is small
                                    >
                                        {positionDisplayNames[position]}
                                        {appearance.position === position && <IconCheck className="ml-2 size-4" />}
                                    </LemonButton>
                                ))}
                            </div>
                            <div className="flex flex-col gap-1 items-start w-60">
                                {surveyType === SurveyType.Widget &&
                                    appearance.widgetType === SurveyWidgetType.Selector && (
                                        <LemonButton
                                            key={SurveyPosition.NextToTrigger}
                                            type="tertiary"
                                            size="small"
                                            fullWidth
                                            onClick={() =>
                                                onAppearanceChange({ position: SurveyPosition.NextToTrigger })
                                            }
                                            active={appearance.position === SurveyPosition.NextToTrigger}
                                            disabled={!surveysStylingAvailable}
                                        >
                                            {positionDisplayNames[SurveyPosition.NextToTrigger]}
                                            {appearance.position === SurveyPosition.NextToTrigger && (
                                                <IconCheck className="ml-2 size-4" />
                                            )}
                                        </LemonButton>
                                    )}
                            </div>
                        </LemonField.Pure>
                    </div>
                    <LemonDivider />

                    {customizeRatingButtons && (
                        <div className="flex gap-4 items-start">
                            <LemonField.Pure label="Rating button color" className="flex-1 gap-1">
                                <LemonInput
                                    value={appearance.ratingButtonColor}
                                    onChange={(ratingButtonColor) => onAppearanceChange({ ratingButtonColor })}
                                    disabled={!surveysStylingAvailable}
                                    className={clsx(
                                        validationErrors?.ratingButtonColor
                                            ? 'border-danger'
                                            : IGNORE_ERROR_BORDER_CLASS
                                    )}
                                />
                                {validationErrors?.ratingButtonColor && (
                                    <LemonField.Error error={validationErrors?.ratingButtonColor} />
                                )}
                            </LemonField.Pure>
                            <LemonField.Pure label="Rating button active color" className="flex-1 gap-1">
                                <LemonInput
                                    value={appearance.ratingButtonActiveColor}
                                    onChange={(ratingButtonActiveColor) =>
                                        onAppearanceChange({ ratingButtonActiveColor })
                                    }
                                    disabled={!surveysStylingAvailable}
                                    className={clsx(
                                        validationErrors?.ratingButtonActiveColor
                                            ? 'border-danger'
                                            : IGNORE_ERROR_BORDER_CLASS
                                    )}
                                />
                                {validationErrors?.ratingButtonActiveColor && (
                                    <LemonField.Error error={validationErrors?.ratingButtonActiveColor} />
                                )}
                            </LemonField.Pure>
                        </div>
                    )}

                    <div className="flex gap-4 items-start">
                        <LemonField.Pure label="Button color" className="flex-1 gap-1">
                            <LemonInput
                                value={appearance.submitButtonColor}
                                onChange={(submitButtonColor) => onAppearanceChange({ submitButtonColor })}
                                disabled={!surveysStylingAvailable}
                                className={clsx(
                                    validationErrors?.submitButtonColor ? 'border-danger' : IGNORE_ERROR_BORDER_CLASS
                                )}
                            />
                            {validationErrors?.submitButtonColor && (
                                <LemonField.Error error={validationErrors?.submitButtonColor} />
                            )}
                        </LemonField.Pure>
                        <LemonField.Pure label="Button text color" className="flex-1 gap-1">
                            <LemonInput
                                value={appearance.submitButtonTextColor}
                                onChange={(submitButtonTextColor) => onAppearanceChange({ submitButtonTextColor })}
                                disabled={!surveysStylingAvailable}
                                className={clsx(
                                    validationErrors?.submitButtonTextColor
                                        ? 'border-danger'
                                        : IGNORE_ERROR_BORDER_CLASS
                                )}
                            />
                            {validationErrors?.submitButtonTextColor && (
                                <LemonField.Error error={validationErrors?.submitButtonTextColor} />
                            )}
                        </LemonField.Pure>
                    </div>

                    <LemonField.Pure
                        label="Survey form zIndex"
                        info="If the survey popup is hidden, set this value higher than the overlapping element's zIndex."
                        className="gap-1"
                    >
                        <LemonInput
                            type="number"
                            value={appearance.zIndex !== undefined ? Number(appearance.zIndex) : undefined}
                            onChange={(val) =>
                                onAppearanceChange({ zIndex: val === undefined ? undefined : String(val) })
                            }
                            disabled={!surveysStylingAvailable}
                            placeholder="e.g. 2147482647"
                            className={IGNORE_ERROR_BORDER_CLASS}
                        />
                    </LemonField.Pure>

                    {customizePlaceholderText && (
                        <LemonField.Pure label="Placeholder text" className="gap-1">
                            <LemonInput
                                value={appearance.placeholder}
                                onChange={(placeholder) => onAppearanceChange({ placeholder })}
                                disabled={!surveysStylingAvailable}
                                className={IGNORE_ERROR_BORDER_CLASS}
                            />
                        </LemonField.Pure>
                    )}

                    <LemonField.Pure
                        label="Font family"
                        info="Custom font selection requires at least version 1.223.4 of posthog-js"
                        className="gap-1"
                    >
                        <LemonSelect
                            value={appearance?.fontFamily}
                            onChange={(fontFamily) => onAppearanceChange({ ...appearance, fontFamily })}
                            options={WEB_SAFE_FONTS.map((font) => {
                                return {
                                    label: (
                                        <span className={font.value.toLowerCase().replace(/\s/g, '-')}>
                                            {font.label}
                                        </span>
                                    ),
                                    value: font.value,
                                }
                            })}
                            className="ignore-error-border"
                        />
                    </LemonField.Pure>

                    <LemonCheckbox
                        label="Hide PostHog branding"
                        onChange={(checked) =>
                            guardAvailableFeature(AvailableFeature.WHITE_LABELLING, () =>
                                onAppearanceChange({ whiteLabel: checked })
                            )
                        }
                        checked={!!appearance.whiteLabel}
                        disabled={!surveysStylingAvailable && !appearance.whiteLabel}
                    />
                </div>
                <div className="flex flex-[1.5] flex-col items-center justify-start rounded overflow-hidden">
                    <LemonTabs
                        activeKey={activeScreenSize}
                        onChange={(key) => setActiveScreenSize(key as PreviewScreenSize)}
                        tabs={[
                            { key: 'desktop', label: 'Desktop Web' },
                            { key: 'tablet', label: 'Tablet Web' },
                            { key: 'mobile', label: 'Mobile Web' },
                        ]}
                        className="m-0"
                    />
                    <LemonSelect
                        onChange={(pageIndex) => setSelectedPageIndex(pageIndex)}
                        className="whitespace-nowrap max-w-xs w-full mb-2"
                        value={selectedPageIndex || 0}
                        options={[
                            ...survey.questions.map((question, index) => ({
                                label: `${index + 1}. ${question.question || 'Untitled Question'}`,
                                value: index,
                            })),
                            ...(appearance.displayThankYouMessage
                                ? [
                                      {
                                          label: `${survey.questions.length + 1}. Confirmation`,
                                          value: survey.questions.length,
                                      },
                                  ]
                                : []),
                        ]}
                    />
                    <div
                        className={clsx(
                            'border border-border max-w-full overflow-hidden rounded-md bg-fill-primary shadow-lg flex items-center justify-center relative transition-[width,height,max-height] duration-300 ease-in-out'
                        )}
                        // easier to use inline-styles for this very specific case
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            width: currentDimensions.width,
                            height: currentDimensions.height,
                            maxHeight: activeScreenSize === 'desktop' ? 'calc(100% - 4rem)' : currentDimensions.height,
                        }}
                    >
                        <SurveyAppearancePreview
                            survey={survey}
                            previewPageIndex={selectedPageIndex || 0}
                            positionStyles={surveyPositioningStyles}
                            onPreviewSubmit={(response) => {
                                const nextStep = getNextSurveyStep(survey, selectedPageIndex, response)
                                if (
                                    nextStep === SurveyQuestionBranchingType.End &&
                                    !survey.appearance?.displayThankYouMessage
                                ) {
                                    return
                                }
                                setSelectedPageIndex(
                                    nextStep === SurveyQuestionBranchingType.End ? survey.questions.length : nextStep
                                )
                            }}
                        />
                    </div>
                </div>
            </LemonModal.Content>
            <LemonModal.Footer>
                <LemonButton type="secondary" onClick={onClose}>
                    Close
                </LemonButton>
            </LemonModal.Footer>
        </LemonModal>
    )
}
