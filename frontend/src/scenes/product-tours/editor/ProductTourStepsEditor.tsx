import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconChevronDown, IconCursorClick, IconEye, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonMenu, LemonModal, LemonSegmentedButton } from '@posthog/lemon-ui'

import { PositionSelector } from 'scenes/surveys/survey-appearance/SurveyAppearancePositionSelector'

import {
    PRODUCT_TOUR_STEP_WIDTHS,
    ProductTourProgressionTriggerType,
    ProductTourStep,
    ProductTourStepType,
    ScreenPosition,
    SurveyPosition,
} from '~/types'

import { ProductTourPreview } from '../components/ProductTourPreview'
import { ProductToursToolbarButton } from '../components/ProductToursToolbarButton'
import { productTourLogic } from '../productTourLogic'
import { isAnnouncement, isBannerAnnouncement } from '../productToursLogic'
import { createDefaultStep, getStepIcon, getStepLabel, getStepTitle, hasElementTarget } from '../stepUtils'
import { BannerSettingsPanel } from './BannerSettingsPanel'
import { StepButtonsEditor } from './StepButtonsEditor'
import { StepContentEditor } from './StepContentEditor'
import { StepScreenshotThumbnail } from './StepScreenshotThumbnail'
import { SurveyStepEditor } from './SurveyStepEditor'
import { TourSettingsPanel } from './TourSettingsPanel'

export interface ProductTourStepsEditorProps {
    tourId: string
}

export function isPresetWidth(width: number): boolean {
    return Object.values(PRODUCT_TOUR_STEP_WIDTHS).includes(width)
}

export const TOUR_WIDTH_PRESET_OPTIONS = [
    { value: PRODUCT_TOUR_STEP_WIDTHS.compact, label: 'Compact' },
    { value: PRODUCT_TOUR_STEP_WIDTHS.default, label: 'Default' },
    { value: PRODUCT_TOUR_STEP_WIDTHS.wide, label: 'Wide' },
    { value: PRODUCT_TOUR_STEP_WIDTHS['extra-wide'], label: 'Extra wide' },
]

export const TOUR_STEP_MIN_WIDTH = 200
export const TOUR_STEP_MAX_WIDTH = 700

export function ProductTourStepsEditor({ tourId }: ProductTourStepsEditorProps): JSX.Element {
    const { productTour, productTourForm, selectedStepIndex } = useValues(productTourLogic({ id: tourId }))
    const { setProductTourFormValue, setSelectedStepIndex } = useActions(productTourLogic({ id: tourId }))

    const steps = productTourForm.content?.steps ?? []
    const appearance = productTourForm.content?.appearance
    const isAnnouncementMode = productTour ? isAnnouncement(productTour) : false
    const isBannerMode = productTour ? isBannerAnnouncement(productTour) : false
    const [stepToDelete, setStepToDelete] = useState<number | null>(null)
    const [showPreviewModal, setShowPreviewModal] = useState(false)
    const [showScreenshotModal, setShowScreenshotModal] = useState(false)

    const selectedStep = steps[selectedStepIndex]

    const updateSteps = (newSteps: ProductTourStep[]): void => {
        setProductTourFormValue('content', {
            ...productTourForm.content,
            steps: newSteps,
        })
    }

    const addStep = (type: ProductTourStepType): void => {
        const newStep = createDefaultStep(type)
        const newSteps = [...steps, newStep]
        updateSteps(newSteps)
        setSelectedStepIndex(newSteps.length - 1)
    }

    const updateStep = (index: number, updates: Partial<ProductTourStep>): void => {
        const newSteps = [...steps]
        newSteps[index] = { ...newSteps[index], ...updates }
        updateSteps(newSteps)
    }

    const confirmDeleteStep = (): void => {
        if (stepToDelete === null) {
            return
        }
        const newSteps = steps.filter((_, i) => i !== stepToDelete)
        updateSteps(newSteps)
        if (selectedStepIndex >= newSteps.length) {
            setSelectedStepIndex(Math.max(0, newSteps.length - 1))
        }
        setStepToDelete(null)
    }

    const moveStep = (fromIndex: number, direction: 'up' | 'down'): void => {
        const toIndex = direction === 'up' ? fromIndex - 1 : fromIndex + 1
        if (toIndex < 0 || toIndex >= steps.length) {
            return
        }
        const newSteps = [...steps]
        const [moved] = newSteps.splice(fromIndex, 1)
        newSteps.splice(toIndex, 0, moved)
        updateSteps(newSteps)
        setSelectedStepIndex(toIndex)
    }

    if (steps.length === 0) {
        return (
            <div className="flex flex-col items-center justify-center gap-4 p-4 mt-4 overflow-auto border border-dashed rounded">
                <div className="max-w-[400px] p-12 text-center">
                    <IconCursorClick className="text-4xl text-muted mb-4" />
                    <h3 className="m-0 mb-2 text-xl font-semibold">No steps yet</h3>
                    <p className="m-0 text-muted">
                        Use the toolbar on your site to add steps to this tour, then come back here to edit their
                        content.
                    </p>
                </div>
            </div>
        )
    }

    const cardClasses = 'border rounded overflow-hidden'
    const cardHeaderClasses = 'flex items-center justify-between px-3 py-2 bg-surface-primary border-b font-semibold'

    return (
        <div className="flex gap-4 items-start p-4 overflow-auto">
            {/* Sidebar - hidden for announcements */}
            {!isAnnouncementMode && (
                <div className={`flex flex-col w-[220px] min-w-[220px] ${cardClasses}`}>
                    <div className={cardHeaderClasses}>
                        <span className="text-xs font-semibold uppercase tracking-wide text-muted">Steps</span>
                        <LemonMenu
                            items={[
                                {
                                    icon: getStepIcon('modal'),
                                    label: getStepLabel('modal'),
                                    onClick: () => addStep('modal'),
                                },
                                {
                                    icon: getStepIcon('survey'),
                                    label: getStepLabel('survey'),
                                    onClick: () => addStep('survey'),
                                },
                            ]}
                            placement="bottom-end"
                        >
                            <LemonButton size="xsmall" icon={<IconPlus />} tooltip="Add step" />
                        </LemonMenu>
                    </div>

                    <div className="flex flex-1 flex-col gap-1 p-2 overflow-y-auto">
                        {steps.map((step, index) => {
                            const isActive = selectedStepIndex === index
                            return (
                                <button
                                    key={step.id}
                                    type="button"
                                    className={`relative flex gap-2 items-center w-full py-2.5 px-2 text-[0.8125rem] text-left cursor-pointer bg-transparent border-none rounded transition-colors ${
                                        isActive
                                            ? 'text-primary-3000 bg-primary-highlight'
                                            : 'hover:bg-surface-secondary'
                                    }`}
                                    onClick={() => setSelectedStepIndex(index)}
                                >
                                    <span
                                        className={`shrink-0 w-5 text-xs font-medium text-center ${isActive ? 'text-default' : 'text-muted'}`}
                                    >
                                        {index + 1}
                                    </span>
                                    <span
                                        className={`flex shrink-0 items-center justify-center w-4 h-4 text-[0.8125rem] ${isActive ? 'text-default' : 'text-muted'}`}
                                    >
                                        {getStepIcon(step.type)}
                                    </span>
                                    <span className="flex-1 overflow-hidden font-medium truncate">
                                        {getStepTitle(step, index)}
                                    </span>
                                </button>
                            )
                        })}
                    </div>
                </div>
            )}

            {/* Main content wrapper */}
            <div className={`flex flex-1 flex-col gap-4 min-w-[400px] ${isAnnouncementMode ? 'max-w-6xl' : ''}`}>
                {/* Main content */}
                <div className={`flex flex-col ${cardClasses}`}>
                    {selectedStep && (
                        <>
                            {/* Step header */}
                            <div className={cardHeaderClasses}>
                                <div className="flex items-center gap-2">
                                    <span>
                                        {isAnnouncementMode
                                            ? productTourForm.name || 'Announcement'
                                            : getStepTitle(selectedStep, selectedStepIndex)}
                                    </span>
                                </div>
                                {!isAnnouncementMode && (
                                    <div className="flex items-center gap-1">
                                        <LemonButton
                                            size="small"
                                            icon={<IconChevronDown className="rotate-180" />}
                                            onClick={() => moveStep(selectedStepIndex, 'up')}
                                            disabledReason={
                                                selectedStepIndex === 0 ? 'Cannot move first step up' : undefined
                                            }
                                            tooltip="Move up"
                                        />
                                        <LemonButton
                                            size="small"
                                            icon={<IconChevronDown />}
                                            onClick={() => moveStep(selectedStepIndex, 'down')}
                                            disabledReason={
                                                selectedStepIndex === steps.length - 1
                                                    ? 'Cannot move last step down'
                                                    : undefined
                                            }
                                            tooltip="Move down"
                                        />
                                        <LemonButton
                                            size="small"
                                            icon={<IconEye />}
                                            onClick={() => setShowPreviewModal(true)}
                                            tooltip="Preview step"
                                        />
                                        <LemonButton
                                            size="small"
                                            status="danger"
                                            icon={<IconTrash />}
                                            onClick={() => setStepToDelete(selectedStepIndex)}
                                            tooltip="Delete step"
                                        />
                                    </div>
                                )}
                            </div>

                            <div
                                className={`flex flex-col px-5 pt-4 pb-6 overflow-y-auto ${isBannerMode ? '' : 'flex-1'}`}
                            >
                                {selectedStep.type === 'survey' ? (
                                    <div className="flex gap-8 items-start">
                                        <div className="shrink-0 basis-80 max-w-80">
                                            <SurveyStepEditor
                                                survey={selectedStep.survey}
                                                onChange={(survey) => updateStep(selectedStepIndex, { survey })}
                                            />
                                            <div className="mt-4">
                                                <label className="text-sm font-medium block mb-2">Position</label>
                                                <PositionSelector
                                                    value={selectedStep.modalPosition ?? SurveyPosition.MiddleCenter}
                                                    onChange={(position: ScreenPosition) =>
                                                        updateStep(selectedStepIndex, { modalPosition: position })
                                                    }
                                                />
                                            </div>
                                        </div>
                                        <div className="flex-1 min-w-0">
                                            <div className="text-xs text-muted uppercase tracking-wide mb-3">
                                                Preview
                                            </div>
                                            <div className="flex justify-center p-6 bg-[#f0f0f0] rounded min-h-[200px]">
                                                <ProductTourPreview
                                                    step={selectedStep}
                                                    appearance={appearance}
                                                    stepIndex={selectedStepIndex}
                                                    totalSteps={steps.length}
                                                />
                                            </div>
                                        </div>
                                    </div>
                                ) : (
                                    <StepContentEditor tourId={tourId} />
                                )}
                            </div>
                        </>
                    )}
                </div>

                {selectedStep && selectedStep.type !== 'survey' && (
                    <div className="border rounded overflow-hidden">
                        <div className="flex items-center justify-between px-3 py-2 bg-surface-primary border-b font-semibold">
                            <span className="text-xs font-semibold uppercase tracking-wide text-muted">
                                {isBannerMode ? 'Banner settings' : 'Step settings'}
                            </span>
                        </div>
                        <div className="py-3 px-4">
                            {isBannerMode ? (
                                <BannerSettingsPanel
                                    step={selectedStep}
                                    onChange={(step) => updateStep(selectedStepIndex, step)}
                                />
                            ) : (
                                <div className="flex flex-col gap-4">
                                    {/* Element-specific controls */}
                                    {hasElementTarget(selectedStep) && (
                                        <div className="flex flex-col gap-3">
                                            <label className="text-sm font-medium">Target element</label>
                                            <div className="flex items-start gap-4">
                                                <div className="flex flex-col gap-3">
                                                    <div className="flex items-center gap-6">
                                                        <div className="flex flex-col gap-1">
                                                            <label className="text-[0.6875rem] font-medium text-muted uppercase tracking-wide">
                                                                Mode
                                                            </label>
                                                            <LemonSegmentedButton
                                                                size="small"
                                                                value={
                                                                    selectedStep.useManualSelector ? 'manual' : 'auto'
                                                                }
                                                                onChange={(value) =>
                                                                    updateStep(selectedStepIndex, {
                                                                        useManualSelector: value === 'manual',
                                                                    })
                                                                }
                                                                options={[
                                                                    { value: 'auto', label: 'Auto' },
                                                                    { value: 'manual', label: 'CSS selector' },
                                                                ]}
                                                            />
                                                        </div>

                                                        <div className="flex flex-col gap-1">
                                                            <label className="text-[0.6875rem] font-medium text-muted uppercase tracking-wide">
                                                                Advance on
                                                            </label>
                                                            <LemonSegmentedButton
                                                                size="small"
                                                                value={selectedStep.progressionTrigger || 'button'}
                                                                onChange={(value) =>
                                                                    updateStep(selectedStepIndex, {
                                                                        progressionTrigger:
                                                                            value as ProductTourProgressionTriggerType,
                                                                    })
                                                                }
                                                                options={[
                                                                    { value: 'button', label: 'Next button' },
                                                                    { value: 'click', label: 'Element click' },
                                                                ]}
                                                            />
                                                        </div>
                                                    </div>

                                                    {selectedStep.useManualSelector && (
                                                        <LemonInput
                                                            value={selectedStep.selector || ''}
                                                            onChange={(value) =>
                                                                updateStep(selectedStepIndex, {
                                                                    selector: value,
                                                                })
                                                            }
                                                            placeholder="#my-element, .my-class"
                                                            size="small"
                                                            className="font-mono max-w-md"
                                                        />
                                                    )}
                                                </div>

                                                {/* Element preview (auto mode only) */}
                                                {!selectedStep.useManualSelector && (
                                                    <div className="flex items-center gap-3 ml-auto">
                                                        {selectedStep.screenshotMediaId &&
                                                            selectedStep.inferenceData && (
                                                                <button
                                                                    type="button"
                                                                    className="block w-20 aspect-[4/3] overflow-hidden cursor-pointer bg-fill-tertiary border rounded transition-all hover:border-primary hover:ring-1 hover:ring-primary"
                                                                    onClick={() => setShowScreenshotModal(true)}
                                                                >
                                                                    <StepScreenshotThumbnail
                                                                        mediaId={selectedStep.screenshotMediaId}
                                                                        className="w-full h-full object-cover"
                                                                    />
                                                                </button>
                                                            )}
                                                        <ProductToursToolbarButton
                                                            tourId={tourId}
                                                            mode="edit"
                                                            label={
                                                                <div className="flex gap-1">
                                                                    <IconCursorClick />
                                                                    {selectedStep.inferenceData
                                                                        ? 'Change'
                                                                        : 'Select element'}
                                                                </div>
                                                            }
                                                            saveFirst
                                                        />
                                                    </div>
                                                )}
                                            </div>
                                            <LemonButton
                                                size="small"
                                                type="tertiary"
                                                status="danger"
                                                icon={<IconTrash />}
                                                className="self-start"
                                                onClick={() =>
                                                    updateStep(selectedStepIndex, {
                                                        type: 'modal',
                                                        selector: undefined,
                                                        inferenceData: undefined,
                                                        screenshotMediaId: undefined,
                                                        useManualSelector: undefined,
                                                    })
                                                }
                                            >
                                                Remove element
                                            </LemonButton>
                                        </div>
                                    )}

                                    {/* Buttons and position */}
                                    <div
                                        className={`${!hasElementTarget(selectedStep) ? 'flex gap-10' : ''} ${hasElementTarget(selectedStep) ? 'pt-4 border-t border-border' : ''}`}
                                    >
                                        <div className="flex-1 min-w-0">
                                            <StepButtonsEditor
                                                buttons={selectedStep.buttons}
                                                onChange={(buttons) => updateStep(selectedStepIndex, { buttons })}
                                                isTourContext={!isAnnouncementMode}
                                                stepIndex={selectedStepIndex}
                                                totalSteps={steps.length}
                                                layout={!hasElementTarget(selectedStep) ? 'stacked' : 'horizontal'}
                                            />
                                        </div>
                                        {!hasElementTarget(selectedStep) && (
                                            <div className="shrink-0 flex flex-col gap-3">
                                                <div>
                                                    <label className="text-sm font-medium block mb-2">Position</label>
                                                    <PositionSelector
                                                        value={
                                                            selectedStep.modalPosition ?? SurveyPosition.MiddleCenter
                                                        }
                                                        onChange={(position: ScreenPosition) =>
                                                            updateStep(selectedStepIndex, {
                                                                modalPosition: position,
                                                            })
                                                        }
                                                    />
                                                </div>
                                                <ProductToursToolbarButton
                                                    tourId={tourId}
                                                    mode="edit"
                                                    label={
                                                        <div className="flex gap-1">
                                                            <IconCursorClick />
                                                            Attach to element
                                                        </div>
                                                    }
                                                    saveFirst
                                                />
                                            </div>
                                        )}
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>
                )}
            </div>

            {/* Settings panel */}
            <div className="w-[360px] min-w-[360px]">
                <TourSettingsPanel tourId={tourId} />
            </div>

            {/* Delete confirmation modal */}
            <LemonModal
                isOpen={stepToDelete !== null}
                onClose={() => setStepToDelete(null)}
                title="Delete step"
                footer={
                    <>
                        <LemonButton type="secondary" onClick={() => setStepToDelete(null)}>
                            Cancel
                        </LemonButton>
                        <LemonButton type="primary" status="danger" onClick={confirmDeleteStep}>
                            Delete
                        </LemonButton>
                    </>
                }
            >
                <p>
                    Are you sure you want to delete{' '}
                    <strong>{stepToDelete !== null ? getStepTitle(steps[stepToDelete], stepToDelete) : ''}</strong>?
                </p>
                <p className="text-muted mt-2">This action cannot be undone.</p>
            </LemonModal>

            {/* Preview modal */}
            <LemonModal
                isOpen={showPreviewModal}
                onClose={() => setShowPreviewModal(false)}
                title={`Preview: ${getStepTitle(selectedStep, selectedStepIndex)}`}
                width={800}
            >
                <div className="flex justify-center items-center p-8 bg-[#f0f0f0] rounded min-h-[300px]">
                    {selectedStep && (
                        <ProductTourPreview
                            step={selectedStep}
                            appearance={appearance}
                            stepIndex={selectedStepIndex}
                            totalSteps={steps.length}
                        />
                    )}
                </div>
            </LemonModal>

            {selectedStep?.screenshotMediaId && (
                <LemonModal
                    isOpen={showScreenshotModal}
                    onClose={() => setShowScreenshotModal(false)}
                    title="Element screenshot"
                    width="auto"
                >
                    <img
                        src={`/uploaded_media/${selectedStep.screenshotMediaId}`}
                        alt="Element screenshot"
                        className="max-w-full max-h-[70vh]"
                    />
                </LemonModal>
            )}
        </div>
    )
}
