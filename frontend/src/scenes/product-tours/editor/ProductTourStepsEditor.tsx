import './ProductTourStepsEditor.scss'

import { JSONContent } from '@tiptap/core'
import { useState } from 'react'

import {
    IconChevronLeft,
    IconChevronRight,
    IconCursorClick,
    IconEye,
    IconMessage,
    IconQuestion,
    IconTrash,
} from '@posthog/icons'
import { LemonBadge, LemonButton, LemonModal } from '@posthog/lemon-ui'

import { PositionSelector } from 'scenes/surveys/survey-appearance/SurveyAppearancePositionSelector'

import {
    PRODUCT_TOUR_STEP_WIDTHS,
    ProductTourAppearance,
    ProductTourStep,
    ProductTourStepType,
    ProductTourStepWidth,
    ScreenPosition,
    SurveyPosition,
} from '~/types'

import { ProductTourPreview } from '../components/ProductTourPreview'
import { StepButtonsEditor } from './StepButtonsEditor'
import { StepContentEditor } from './StepContentEditor'
import { StepLayoutSettings } from './StepLayoutSettings'
import { StepScreenshotThumbnail } from './StepScreenshotThumbnail'
import { SurveyStepEditor } from './SurveyStepEditor'

export interface ProductTourStepsEditorProps {
    steps: ProductTourStep[]
    appearance?: ProductTourAppearance
    onChange: (steps: ProductTourStep[]) => void
}

const STEP_TYPE_ICONS: Partial<Record<ProductTourStepType, JSX.Element>> = {
    element: <IconCursorClick />,
    modal: <IconMessage />,
    survey: <IconQuestion />,
}

const STEP_TYPE_LABELS: Partial<Record<ProductTourStepType, string>> = {
    element: 'Element',
    modal: 'Modal',
    survey: 'Survey',
}

function getStepTitle(step: ProductTourStep, index: number): string {
    if (step.content && typeof step.content === 'object') {
        const doc = step.content as JSONContent
        const firstContent = doc.content?.[0]
        if (firstContent?.content?.[0]?.text) {
            const text = firstContent.content[0].text
            return text.length > 30 ? text.slice(0, 30) + '...' : text
        }
    }
    return `Step ${index + 1}`
}

export function getWidthValue(maxWidth: ProductTourStep['maxWidth']): number {
    if (typeof maxWidth === 'number') {
        return maxWidth
    }
    if (maxWidth && maxWidth in PRODUCT_TOUR_STEP_WIDTHS) {
        return PRODUCT_TOUR_STEP_WIDTHS[maxWidth as ProductTourStepWidth]
    }
    return PRODUCT_TOUR_STEP_WIDTHS.default
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

export function ProductTourStepsEditor({ steps, appearance, onChange }: ProductTourStepsEditorProps): JSX.Element {
    const [selectedStepIndex, setSelectedStepIndex] = useState<number>(0)
    const [stepToDelete, setStepToDelete] = useState<number | null>(null)
    const [showPreviewModal, setShowPreviewModal] = useState(false)
    const [showScreenshotModal, setShowScreenshotModal] = useState(false)

    const selectedStep = steps[selectedStepIndex]

    const updateStep = (index: number, updates: Partial<ProductTourStep>): void => {
        const newSteps = [...steps]
        newSteps[index] = { ...newSteps[index], ...updates }
        onChange(newSteps)
    }

    const confirmDeleteStep = (): void => {
        if (stepToDelete === null) {
            return
        }
        const newSteps = steps.filter((_, i) => i !== stepToDelete)
        onChange(newSteps)
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
        onChange(newSteps)
        setSelectedStepIndex(toIndex)
    }

    if (steps.length === 0) {
        return (
            <div className="ProductTourStepsEditor ProductTourStepsEditor--empty">
                <div className="ProductTourStepsEditor__empty-state">
                    <IconCursorClick className="text-4xl text-muted mb-4" />
                    <h3>No steps yet</h3>
                    <p className="text-muted mb-4">
                        Use the toolbar on your site to add steps to this tour, then come back here to edit their
                        content.
                    </p>
                </div>
            </div>
        )
    }

    return (
        <div className="ProductTourStepsEditor">
            {/* Sidebar */}
            <div className="ProductTourStepsEditor__sidebar">
                <div className="ProductTourStepsEditor__sidebar-header">
                    <span className="font-semibold">Steps</span>
                </div>

                <div className="ProductTourStepsEditor__sidebar-list">
                    {steps.map((step, index) => (
                        <button
                            key={step.id}
                            type="button"
                            className={`ProductTourStepsEditor__sidebar-item ${
                                selectedStepIndex === index ? 'active' : ''
                            }`}
                            onClick={() => setSelectedStepIndex(index)}
                        >
                            <span className="ProductTourStepsEditor__sidebar-item-icon">
                                {STEP_TYPE_ICONS[step.type]}
                            </span>
                            <span className="ProductTourStepsEditor__sidebar-item-title">
                                {getStepTitle(step, index)}
                            </span>
                            <LemonBadge.Number count={index + 1} size="small" />
                        </button>
                    ))}
                </div>
            </div>

            {/* Main content */}
            <div className="ProductTourStepsEditor__main">
                {selectedStep && (
                    <>
                        {/* Step header */}
                        <div className="ProductTourStepsEditor__step-header">
                            <div className="flex items-center gap-2">
                                <LemonBadge.Number count={selectedStepIndex + 1} size="medium" />
                                <span className="font-semibold">{STEP_TYPE_LABELS[selectedStep.type]} step</span>
                                {selectedStep.type === 'element' && (
                                    <>
                                        {selectedStep.screenshotMediaId && (
                                            <StepScreenshotThumbnail
                                                mediaId={selectedStep.screenshotMediaId}
                                                onClick={() => setShowScreenshotModal(true)}
                                            />
                                        )}
                                        {selectedStep.selector && (
                                            <code className="text-xs bg-fill-primary px-2 py-0.5 rounded">
                                                {selectedStep.selector}
                                            </code>
                                        )}
                                    </>
                                )}
                            </div>
                            <div className="flex items-center gap-2">
                                <LemonButton
                                    size="small"
                                    icon={<IconChevronLeft />}
                                    onClick={() => moveStep(selectedStepIndex, 'up')}
                                    disabledReason={selectedStepIndex === 0 ? 'First step' : undefined}
                                    tooltip="Move up"
                                />
                                <LemonButton
                                    size="small"
                                    icon={<IconChevronRight />}
                                    onClick={() => moveStep(selectedStepIndex, 'down')}
                                    disabledReason={selectedStepIndex === steps.length - 1 ? 'Last step' : undefined}
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
                        </div>

                        {selectedStep.type === 'survey' ? (
                            <div className="ProductTourStepsEditor__survey-layout">
                                <div className="ProductTourStepsEditor__survey-editor">
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
                                <div className="ProductTourStepsEditor__survey-preview">
                                    <div className="text-xs text-muted uppercase tracking-wide mb-3">Preview</div>
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
                            <>
                                {/* Rich content editor */}
                                <StepContentEditor
                                    content={selectedStep.content as JSONContent | null}
                                    onChange={(content) => updateStep(selectedStepIndex, { content })}
                                    placeholder={`Type '/' for commands, or start writing your step ${selectedStepIndex + 1} content...`}
                                />

                                {/* Step configuration */}
                                <div className="mt-4 p-4 bg-fill-primary rounded-lg space-y-6">
                                    <StepButtonsEditor
                                        buttons={selectedStep.buttons}
                                        onChange={(buttons) => updateStep(selectedStepIndex, { buttons })}
                                        isTourContext={true}
                                        stepIndex={selectedStepIndex}
                                        totalSteps={steps.length}
                                        layout="horizontal"
                                    />

                                    <div>
                                        <div className="text-xs font-semibold text-muted uppercase tracking-wide mb-3">
                                            Layout
                                        </div>
                                        <StepLayoutSettings
                                            step={selectedStep}
                                            onChange={(updates) => updateStep(selectedStepIndex, updates)}
                                            showPosition={selectedStep.type === 'modal'}
                                        />
                                    </div>
                                </div>
                            </>
                        )}
                    </>
                )}
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
