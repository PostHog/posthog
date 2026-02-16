import { useActions, useValues } from 'kea'

import { IconCursorClick, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSegmentedButton, LemonSlider, Tooltip } from '@posthog/lemon-ui'

import { PositionSelector } from 'scenes/surveys/survey-appearance/SurveyAppearancePositionSelector'

import { ScreenPosition, SurveyPosition } from '~/types'

import { StepButtonsEditor } from '../editor/StepButtonsEditor'
import { StepScreenshotThumbnail } from '../editor/StepScreenshotThumbnail'
import { productTourLogic } from '../productTourLogic'
import { isAnnouncement } from '../productToursLogic'
import { hasElementTarget, hasIncompleteTargeting } from '../stepUtils'

export interface StepSettingsPanelProps {
    tourId: string
}

function ElementEmptyState({ onClick }: { onClick: () => void }): JSX.Element {
    return (
        <div className="flex items-center gap-3 p-3 border border-dashed rounded text-muted text-sm">
            <span>Add an element from your page to display this step as a tooltip.</span>
            <LemonButton size="small" type="secondary" icon={<IconPlus />} onClick={onClick}>
                Add element
            </LemonButton>
        </div>
    )
}

function ElementSettings({ tourId }: StepSettingsPanelProps): JSX.Element | null {
    const { productTourForm, selectedStepIndex } = useValues(productTourLogic({ id: tourId }))
    const { updateSelectedStep, submitAndOpenToolbar } = useActions(productTourLogic({ id: tourId }))

    const steps = productTourForm.content?.steps ?? []
    const step = steps[selectedStepIndex]

    if (!step) {
        return null
    }

    const hasTarget = hasElementTarget(step)

    if (step.elementTargeting === undefined) {
        return <ElementEmptyState onClick={() => updateSelectedStep({ elementTargeting: 'auto' })} />
    }

    return (
        <div className="flex flex-col gap-3 p-3 border rounded">
            <div className="flex gap-6 items-start justify-between">
                <div className="flex flex-col gap-4 flex-1 min-w-0">
                    <div className="flex items-center gap-6">
                        <div className="flex flex-col gap-1">
                            <Tooltip
                                title="Choose to use our automatic targeting to find your element, or provide a CSS selector for manual targeting."
                                docLink="https://posthog.com/docs/product-tours/element-selection"
                            >
                                <label className="text-[0.6875rem] font-medium text-muted uppercase tracking-wide">
                                    Targeting Mode
                                </label>
                            </Tooltip>
                            <LemonSegmentedButton
                                size="small"
                                value={step.elementTargeting ?? 'auto'}
                                onChange={(value) => updateSelectedStep({ elementTargeting: value })}
                                options={[
                                    { value: 'auto', label: 'Auto' },
                                    { value: 'manual', label: 'CSS selector' },
                                ]}
                            />
                        </div>

                        <div className="flex flex-col gap-1">
                            <Tooltip
                                title="Choose how your tour goes to the next step - when users click a Next button, or when they click the target element."
                                docLink="https://posthog.com/docs/product-tours/tour-progression"
                            >
                                <label className="text-[0.6875rem] font-medium text-muted uppercase tracking-wide">
                                    Next step on...
                                </label>
                            </Tooltip>
                            <LemonSegmentedButton
                                size="small"
                                value={step.progressionTrigger || 'button'}
                                onChange={(value) => updateSelectedStep({ progressionTrigger: value })}
                                options={[
                                    { value: 'button', label: 'Next button' },
                                    { value: 'click', label: 'Element click' },
                                ]}
                            />
                        </div>
                    </div>

                    {step.elementTargeting === 'auto' && step.inferenceData && (
                        <div className="flex items-start gap-6 pt-2">
                            {/* only show text matching if there is text to match against */}
                            {step.inferenceData?.text && (
                                <div className="flex flex-col gap-1">
                                    <Tooltip
                                        title="Whether this element's text is static or dynamic (e.g. 'Hello, {name}!'). When set to 'Dynamic', PostHog will not attempt to find your element based on its text content."
                                        docLink="https://posthog.com/docs/product-tours/element-selection#dynamic-text"
                                    >
                                        <label className="text-[0.6875rem] font-medium text-muted uppercase tracking-wide">
                                            Text matching
                                        </label>
                                    </Tooltip>
                                    <LemonSegmentedButton
                                        size="small"
                                        value={step.inferenceData?.excludeText ? 'dynamic' : 'static'}
                                        onChange={(value) =>
                                            step.inferenceData &&
                                            updateSelectedStep({
                                                inferenceData: {
                                                    ...step.inferenceData,
                                                    excludeText: value === 'dynamic',
                                                },
                                            })
                                        }
                                        options={[
                                            { value: 'static', label: 'Static' },
                                            { value: 'dynamic', label: 'Dynamic' },
                                        ]}
                                    />
                                </div>
                            )}
                            <div className="min-w-[200px]">
                                <Tooltip
                                    title="How strictly we should identify the target element. Reduce if the tour is failing to find your element."
                                    docLink="https://posthog.com/docs/product-tours/element-selection#targeting-precision"
                                >
                                    <label className="text-[0.6875rem] font-medium text-muted uppercase tracking-wide block mb-1">
                                        Precision
                                    </label>
                                </Tooltip>
                                <LemonSlider
                                    min={0}
                                    max={1}
                                    step={0.1}
                                    value={step.inferenceData?.precision ?? 1}
                                    onChange={(value) =>
                                        step.inferenceData &&
                                        updateSelectedStep({
                                            inferenceData: {
                                                ...step.inferenceData,
                                                precision: value,
                                            },
                                        })
                                    }
                                />
                                <div className="flex justify-between text-[0.625rem] text-muted">
                                    <span>Loose</span>
                                    <span>Strict</span>
                                </div>
                            </div>
                        </div>
                    )}
                </div>

                {step.screenshotMediaId && (
                    <div className="flex flex-col items-center gap-3 ml-auto">
                        <StepScreenshotThumbnail mediaId={step.screenshotMediaId} />
                    </div>
                )}
            </div>

            {step.elementTargeting === 'manual' && (
                <div className="flex flex-col gap-1 flex-1 min-w-0">
                    <label className="text-[0.6875rem] font-medium text-muted uppercase tracking-wide">
                        CSS Selector
                    </label>
                    <LemonInput
                        value={step.selector || ''}
                        onChange={(value) => updateSelectedStep({ selector: value })}
                        placeholder="#my-element"
                        size="small"
                        className="font-mono max-w-md"
                        autoFocus={!hasTarget}
                    />
                </div>
            )}

            {step.elementTargeting === 'auto' && (
                <div className="flex flex-col gap-1">
                    <label className="text-[0.6875rem] font-medium text-muted uppercase tracking-wide">Element</label>
                    <div className="flex gap-2">
                        <LemonButton
                            size="small"
                            type="secondary"
                            icon={<IconCursorClick />}
                            onClick={() => submitAndOpenToolbar('edit')}
                        >
                            {step.inferenceData ? 'Change' : 'Select element in Toolbar'}
                        </LemonButton>
                        {step.inferenceData && (
                            <LemonButton
                                size="small"
                                type="secondary"
                                status="danger"
                                icon={<IconTrash />}
                                onClick={() =>
                                    updateSelectedStep({
                                        selector: undefined,
                                        inferenceData: undefined,
                                        screenshotMediaId: undefined,
                                        useManualSelector: undefined,
                                        elementTargeting: undefined,
                                    })
                                }
                            >
                                Remove
                            </LemonButton>
                        )}
                    </div>
                </div>
            )}

            {step.elementTargeting && hasIncompleteTargeting(step) && (
                <div className="flex flex-col items-start gap-2">
                    <span className="text-muted">
                        {step.elementTargeting === 'auto'
                            ? 'Choose an element on your page with the Toolbar, or use a CSS selector instead.'
                            : 'Enter a CSS selector above, or swap to "Auto" and choose an element on your page with the Toolbar.'}
                    </span>
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        status="danger"
                        icon={<IconTrash />}
                        className=""
                        onClick={() =>
                            updateSelectedStep({
                                selector: undefined,
                                inferenceData: undefined,
                                screenshotMediaId: undefined,
                                useManualSelector: undefined,
                                elementTargeting: undefined,
                            })
                        }
                    >
                        Remove element
                    </LemonButton>
                </div>
            )}
        </div>
    )
}

export function StepSettings({ tourId }: StepSettingsPanelProps): JSX.Element | null {
    const { productTour, productTourForm, selectedStepIndex } = useValues(productTourLogic({ id: tourId }))
    const { updateSelectedStep } = useActions(productTourLogic({ id: tourId }))

    const isAnnouncementMode = productTour ? isAnnouncement(productTour) : false

    const steps = productTourForm.content?.steps ?? []
    const step = steps[selectedStepIndex]

    if (!step) {
        return null
    }

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
                <label className="text-sm font-medium">Target element</label>
                <ElementSettings tourId={tourId} />
            </div>

            <div className="flex gap-5">
                <div className="shrink-0 flex flex-col gap-3">
                    <div>
                        <label className="text-sm font-medium block mb-2">Position</label>
                        <PositionSelector
                            disabled={step.elementTargeting !== undefined}
                            tooltip={
                                step.elementTargeting !== undefined
                                    ? 'This step will be positioned next to the element you choose.'
                                    : undefined
                            }
                            value={step.modalPosition ?? SurveyPosition.MiddleCenter}
                            onChange={(position: ScreenPosition) =>
                                updateSelectedStep({
                                    modalPosition: position,
                                })
                            }
                        />
                    </div>
                </div>
                <div className="flex-1 min-w-0">
                    <StepButtonsEditor
                        buttons={step.buttons}
                        onChange={(buttons) => updateSelectedStep({ buttons })}
                        isTourContext={!isAnnouncementMode}
                        stepIndex={selectedStepIndex}
                        totalSteps={steps.length}
                        layout="stacked"
                    />
                </div>
            </div>
        </div>
    )
}
