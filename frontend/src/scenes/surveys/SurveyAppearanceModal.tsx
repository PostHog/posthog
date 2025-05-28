import { IconCheck } from '@posthog/icons'
import {
    LemonButton,
    LemonDivider,
    LemonInput,
    LemonModal,
    LemonSelect,
    LemonSwitch,
    LemonTabs,
} from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
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
    [SurveyPosition.Left]: 'Bottom Left',
    [SurveyPosition.Center]: 'Bottom Center',
    [SurveyPosition.Right]: 'Bottom Right',
    [SurveyPosition.NextToTrigger]: 'Next to feedback button',
}

function SurveyOptionsGroup({
    children,
    sectionTitle,
}: {
    children: React.ReactNode
    sectionTitle: string
}): JSX.Element {
    return (
        <div className="grid grid-cols-2 gap-x-2 gap-y-1 items-start">
            <h3 className="col-span-2 mb-0">{sectionTitle}</h3>
            {children}
        </div>
    )
}

const screenDimensions: Record<PreviewScreenSize, { width: string; height: string; scale?: number }> = {
    mobile: { width: '375px', height: '667px' },
    tablet: { width: '768px', height: '1024px' },
    desktop: { width: '100%', height: '100%' },
}

function SurveyPreview(): JSX.Element {
    const { survey, selectedPageIndex } = useValues(surveyLogic)
    const { setSelectedPageIndex } = useActions(surveyLogic)

    const appearance: SurveyAppearance = { ...defaultSurveyAppearance, ...(survey.appearance || {}) }

    const [activeScreenSize, setActiveScreenSize] = useState<PreviewScreenSize>('desktop')
    const [surveyPreviewBackground, setSurveyPreviewBackground] = useState<'light' | 'dark'>('light')

    const currentDimensions = screenDimensions[activeScreenSize]
    return (
        <div className="flex flex-[1.5] flex-col items-center justify-start rounded overflow-hidden gap-2">
            <LemonTabs
                activeKey={activeScreenSize}
                onChange={(key) => setActiveScreenSize(key as PreviewScreenSize)}
                tabs={[
                    { key: 'desktop', label: 'Desktop Web' },
                    { key: 'tablet', label: 'Tablet Web' },
                    { key: 'mobile', label: 'Mobile Web' },
                ]}
                barClassName="mb-0"
            />
            <div className="flex flex-col md:flex-row gap-2 md:items-center md:justify-between flex-1 min-w-full max-w-full">
                <LemonField.Pure
                    label="Current question"
                    className="gap-1 max-w-full md:max-w-sm"
                    htmlFor="survey-preview-question-select"
                >
                    <LemonSelect
                        onChange={(pageIndex) => setSelectedPageIndex(pageIndex)}
                        className="whitespace-nowrap max-w-fit"
                        value={selectedPageIndex || 0}
                        id="survey-preview-question-select"
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
                </LemonField.Pure>
                <LemonSwitch
                    checked={surveyPreviewBackground === 'light'}
                    onChange={(checked) => setSurveyPreviewBackground(checked ? 'light' : 'dark')}
                    label={surveyPreviewBackground === 'light' ? 'Light background' : 'Dark background'}
                    className="md:self-end"
                />
            </div>
            <div
                className={clsx(
                    'border border-border max-w-full overflow-hidden rounded-md shadow-lg flex items-center justify-center relative transition-[width,height,max-height] duration-300 ease-in-out',
                    surveyPreviewBackground === 'light' ? 'bg-white' : 'bg-black'
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
                    positionStyles={{
                        position: 'absolute',
                    }}
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
    )
}

export function SurveyAppearanceModal({ visible, onClose }: SurveyAppearanceModalProps): JSX.Element | null {
    const { survey, surveyErrors } = useValues(surveyLogic)
    const { setSurveyValue } = useActions(surveyLogic)
    const { surveysStylingAvailable } = useValues(surveysLogic)

    const appearance: SurveyAppearance = { ...defaultSurveyAppearance, ...(survey.appearance || {}) }
    const validationErrors = surveyErrors?.appearance
    const surveyType = survey.type

    const onAppearanceChange = (newAppearance: Partial<SurveyAppearance>): void => {
        setSurveyValue('appearance', { ...appearance, ...newAppearance })
    }

    const customizeRatingButtons = survey.questions.some((question) => question.type === SurveyQuestionType.Rating)
    const customizePlaceholderText = survey.questions.some((question) => question.type === SurveyQuestionType.Open)

    if (survey.type === SurveyType.API) {
        return null
    }

    return (
        <LemonModal isOpen={visible} onClose={onClose} fullScreen simple>
            <LemonModal.Header>Customize Survey Apperance</LemonModal.Header>
            <LemonModal.Content className="flex flex-col md:flex-row flex-1 h-full gap-4 overflow-hidden">
                <div className="flex-1 overflow-y-auto flex flex-col gap-2 pr-1">
                    {!surveysStylingAvailable && (
                        <PayGateMini feature={AvailableFeature.SURVEYS_STYLING} className="mb-4">
                            <></>
                        </PayGateMini>
                    )}

                    <SurveyOptionsGroup sectionTitle="Container options">
                        <span className="col-span-2 text-secondary">
                            These options are only applied in the web surveys. Not on native mobile apps.
                        </span>
                        <LemonField.Pure label="Max width" className="flex-1 gap-1">
                            <LemonInput
                                value={appearance.maxWidth}
                                onChange={(maxWidth) => onAppearanceChange({ maxWidth })}
                                disabled={!surveysStylingAvailable}
                                className={IGNORE_ERROR_BORDER_CLASS}
                            />
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
                                disabled={!surveysStylingAvailable}
                            />
                        </LemonField.Pure>
                        <LemonField.Pure label="Border radius" className="flex-1 gap-1">
                            <LemonInput
                                value={appearance.borderRadius || defaultSurveyAppearance.borderRadius}
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
                                disabled={!surveysStylingAvailable}
                            />
                        </LemonField.Pure>
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
                    </SurveyOptionsGroup>
                    <LemonDivider />

                    <SurveyOptionsGroup sectionTitle="Colors and placeholder customization">
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
                        {customizeRatingButtons && (
                            <>
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
                            </>
                        )}
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
                    </SurveyOptionsGroup>
                </div>
                <SurveyPreview />
            </LemonModal.Content>
            <LemonModal.Footer>
                <LemonButton type="secondary" onClick={onClose}>
                    Close
                </LemonButton>
            </LemonModal.Footer>
        </LemonModal>
    )
}
