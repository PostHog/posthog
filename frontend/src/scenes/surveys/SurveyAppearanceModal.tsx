import { LemonButton, LemonCheckbox, LemonInput, LemonModal, LemonSelect, LemonTabs } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { useState } from 'react'

import {
    AvailableFeature,
    SurveyAppearance,
    SurveyPosition,
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

export function SurveyAppearanceModal({ visible, onClose }: SurveyAppearanceModalProps): JSX.Element | null {
    const { survey, surveyErrors } = useValues(surveyLogic)
    const { setSurveyValue } = useActions(surveyLogic)
    const { surveysStylingAvailable } = useValues(surveysLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)

    const [activeScreenSize, setActiveScreenSize] = useState<PreviewScreenSize>('desktop')
    const [previewPageIndex, setPreviewPageIndex] = useState(0)

    const appearance: SurveyAppearance = { ...defaultSurveyAppearance, ...(survey.appearance || {}) }
    const validationErrors = surveyErrors?.appearance
    const surveyType = survey.type

    const onAppearanceChange = (newAppearance: Partial<SurveyAppearance>): void => {
        setSurveyValue('appearance', { ...appearance, ...newAppearance })
    }

    const customizeRatingButtons = survey.questions.some((question) => question.type === SurveyQuestionType.Rating)
    const customizePlaceholderText = survey.questions.some((question) => question.type === SurveyQuestionType.Open)

    const screenDimensions: Record<PreviewScreenSize, { width: string; height: string; scale?: number }> = {
        mobile: { width: '375px', height: '667px', scale: 0.85 },
        tablet: { width: '768px', height: '1024px', scale: 0.65 },
        desktop: { width: '100%', height: '100%', scale: 1 },
    }

    const currentDimensions = screenDimensions[activeScreenSize]

    if (survey.type === SurveyType.API) {
        return null
    }

    const isNotDesktop = activeScreenSize !== 'desktop'

    const surveyPositioningStyles: React.CSSProperties = {
        position: 'absolute',
        ...(isNotDesktop && {
            maxWidth: '85%',
        }),
    }

    return (
        <LemonModal isOpen={visible} onClose={onClose} fullScreen simple>
            <LemonModal.Header>Customize Survey Apperance</LemonModal.Header>
            <LemonModal.Content className="flex flex-row flex-1 h-full gap-4 overflow-hidden">
                {/* Left side: Customization Options */}
                <div className="flex-1 overflow-y-auto flex flex-col gap-2 pr-1">
                    <h3 className="sticky top-0 bg-bg-light py-2 z-10">Options</h3>
                    {!surveysStylingAvailable && (
                        <PayGateMini feature={AvailableFeature.SURVEYS_STYLING} className="mb-4">
                            <></>
                        </PayGateMini>
                    )}

                    <div className="flex gap-4 items-start">
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
                    </div>

                    <LemonField.Pure
                        label="Position"
                        info={
                            surveyType === SurveyType.Widget && appearance.widgetType === SurveyWidgetType.Selector
                                ? 'The "next to feedback button" option requires posthog.js version 1.235.2 or higher.'
                                : undefined
                        }
                        className="gap-1"
                    >
                        <div className="flex gap-1 flex-wrap">
                            {Object.values(SurveyPosition).map((position) => {
                                if (
                                    position === SurveyPosition.NextToTrigger &&
                                    !(
                                        surveyType === SurveyType.Widget &&
                                        appearance.widgetType === SurveyWidgetType.Selector
                                    )
                                ) {
                                    return null
                                }
                                return (
                                    <LemonButton
                                        key={position}
                                        tooltip={
                                            position === SurveyPosition.NextToTrigger
                                                ? 'This option is only available for feedback button surveys.'
                                                : undefined
                                        }
                                        type="tertiary"
                                        size="small"
                                        onClick={() => onAppearanceChange({ position })}
                                        active={appearance.position === position}
                                        disabled={!surveysStylingAvailable}
                                    >
                                        {position === SurveyPosition.NextToTrigger
                                            ? 'Next to feedback button'
                                            : position}
                                    </LemonButton>
                                )
                            })}
                        </div>
                    </LemonField.Pure>

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
                {/* End of options scrollable area */}
                {/* Right side: Preview */}
                <div className="flex flex-[1.5] flex-col items-center bg-conic justify-start rounded overflow-hidden">
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
                        onChange={(pageIndex) => setPreviewPageIndex(pageIndex)}
                        className="whitespace-nowrap max-w-xs w-full mb-2"
                        value={previewPageIndex}
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
                            'border border-border max-w-full overflow-hidden rounded-md bg-bg-light shadow-lg flex items-center justify-center relative transition-[width,height,max-height] duration-300 ease-in-out'
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
                            previewPageIndex={previewPageIndex}
                            positionStyles={surveyPositioningStyles}
                        />
                    </div>
                </div>{' '}
                {/* End of Right Side */}
            </LemonModal.Content>
            <LemonModal.Footer>
                <LemonButton type="secondary" onClick={onClose}>
                    Close
                </LemonButton>
            </LemonModal.Footer>
        </LemonModal>
    )
}
