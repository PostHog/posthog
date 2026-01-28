import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconCheck, IconChevronDown, IconCursorClick, IconExternal, IconPlay, IconPlus, IconX } from '@posthog/icons'
import { LemonButton, LemonInput, LemonMenu } from '@posthog/lemon-ui'

import { STEP_TYPE_ICONS, STEP_TYPE_LABELS } from 'scenes/product-tours/stepUtils'

import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'

import { StepCard } from './StepCard'
import {
    PRODUCT_TOURS_MIN_JS_VERSION,
    TourStep,
    hasMinProductToursVersion,
    productToursLogic,
} from './productToursLogic'
import { PRODUCT_TOURS_SIDEBAR_TRANSITION_MS } from './utils'

const SIDEBAR_WIDTH = 320

export function ProductToursSidebar(): JSX.Element | null {
    const { userIntent, posthog } = useValues(toolbarConfigLogic)
    const {
        selectedTourId,
        tourForm,
        tourFormErrors,
        editorState,
        stepCount,
        expandedStepIndex,
        isTourFormSubmitting,
        isPreviewing,
        pendingEditInPostHog,
    } = useValues(productToursLogic)
    const {
        selectTour,
        saveTour,
        saveAndEditInPostHog,
        previewTour,
        setTourFormValue,
        addStep,
        setExpandedStepIndex,
        setEditorState,
        updateRects,
        setSidebarTransitioning,
    } = useActions(productToursLogic)

    const steps = tourForm?.steps || []

    const [dragIndex, setDragIndex] = useState<number | null>(null)
    const [dropIndex, setDropIndex] = useState<number | null>(null)

    const handleDragStart = (index: number): void => {
        setDragIndex(index)
    }

    const handleDragOver = (e: React.DragEvent, index: number): void => {
        e.preventDefault()
        if (dragIndex !== null && dragIndex !== index) {
            setDropIndex(index)
        }
    }

    const handleDragEnd = (): void => {
        if (dragIndex !== null && dropIndex !== null && dragIndex !== dropIndex) {
            const newSteps = [...steps]
            const [moved] = newSteps.splice(dragIndex, 1)
            newSteps.splice(dropIndex, 0, moved)
            setTourFormValue('steps', newSteps)
        }
        setDragIndex(null)
        setDropIndex(null)
    }

    const getSaveDisabledReason = (): string | undefined => {
        if (stepCount === 0) {
            return 'Add at least one step'
        }

        if (tourFormErrors?.name) {
            return 'Enter a tour name'
        }
    }

    const getPreviewDisabledReason = (): string | undefined => {
        if (posthog?.version && !hasMinProductToursVersion(posthog.version)) {
            return `Requires posthog-js ${PRODUCT_TOURS_MIN_JS_VERSION}+`
        }

        if (isPreviewing) {
            return 'Preview in progress'
        }

        if (stepCount === 0) {
            return 'Add at least one step'
        }
    }

    useEffect(() => {
        if (selectedTourId !== null) {
            document.body.style.transition = `margin-right ${PRODUCT_TOURS_SIDEBAR_TRANSITION_MS}ms ease-out`
            document.body.style.marginRight = `${SIDEBAR_WIDTH}px`

            const timer = setTimeout(() => {
                setSidebarTransitioning(false)
                updateRects()
            }, PRODUCT_TOURS_SIDEBAR_TRANSITION_MS + 50)

            return () => {
                clearTimeout(timer)
                document.body.style.marginRight = ''
            }
        }
    }, [selectedTourId, updateRects, setSidebarTransitioning])

    if (selectedTourId === null) {
        return null
    }

    const isAddingStep = editorState.mode === 'selecting'
    const isNewTour = !tourForm?.id

    return (
        <>
            <div
                className="flex flex-col"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    position: 'fixed',
                    top: 0,
                    right: 0,
                    bottom: 0,
                    width: SIDEBAR_WIDTH,
                    backgroundColor: 'var(--color-bg-3000)',
                    borderLeft: '1px solid var(--border-bold-3000)',
                    boxShadow: '-4px 0 24px rgba(0, 0, 0, 0.4)',
                    zIndex: 2147483019,
                    pointerEvents: 'auto',
                    color: 'var(--text-3000)',
                }}
                onClick={(e) => e.stopPropagation()}
            >
                <div className="p-4 border-b border-border-bold-3000 bg-bg-light">
                    <div className="flex items-center justify-between mb-3">
                        <h2 className="m-0 text-sm font-semibold">{isNewTour ? 'New tour' : 'Edit tour'}</h2>
                        <button
                            type="button"
                            onClick={() => selectTour(null)}
                            className="p-1 rounded border-none bg-transparent cursor-pointer text-muted-3000 hover:text-text-3000 flex items-center justify-center"
                        >
                            <IconX className="w-4 h-4" />
                        </button>
                    </div>

                    <LemonInput
                        placeholder="Tour name"
                        value={tourForm?.name || ''}
                        onChange={(value) => setTourFormValue('name', value)}
                        status={tourFormErrors?.name ? 'danger' : undefined}
                        fullWidth
                    />

                    <div className="mt-3 flex gap-2">
                        <LemonButton
                            type="secondary"
                            icon={<IconPlay />}
                            onClick={previewTour}
                            disabledReason={getPreviewDisabledReason()}
                            center
                            className="flex-1"
                        >
                            Preview
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            icon={<IconCheck />}
                            onClick={saveTour}
                            loading={isTourFormSubmitting && !pendingEditInPostHog}
                            disabledReason={getSaveDisabledReason()}
                            center
                            className="flex-1"
                        >
                            Save
                        </LemonButton>
                    </div>
                </div>

                <div className="flex-1 overflow-y-auto p-4">
                    <div className="flex items-center justify-between mb-3">
                        <span className="text-xs font-semibold text-muted-3000 uppercase tracking-wide">Steps</span>
                        <span className="text-xs text-muted-3000">
                            {steps.length} {steps.length === 1 ? 'step' : 'steps'}
                        </span>
                    </div>

                    {steps.length === 0 && !isAddingStep ? (
                        <div className="text-center py-8 px-4">
                            <div className="w-12 h-12 rounded-full bg-secondary-3000 flex items-center justify-center mx-auto mb-3 text-muted-3000">
                                <IconCursorClick className="w-5 h-5" />
                            </div>
                            <p className="m-0 text-sm mb-1">No steps yet</p>
                            <p className="m-0 text-xs text-muted-3000">Add your first step to get started</p>
                        </div>
                    ) : (
                        <div className="flex flex-col gap-2">
                            {steps.map((step: TourStep, index: number) => (
                                <StepCard
                                    key={step.id}
                                    step={step}
                                    index={index}
                                    isExpanded={expandedStepIndex === index}
                                    onToggleExpand={() =>
                                        setExpandedStepIndex(expandedStepIndex === index ? null : index)
                                    }
                                    onDragStart={() => handleDragStart(index)}
                                    onDragOver={(e) => handleDragOver(e, index)}
                                    onDragEnd={handleDragEnd}
                                    isDragging={dragIndex === index}
                                    isDropTarget={dropIndex === index && dragIndex !== index}
                                />
                            ))}
                        </div>
                    )}

                    <div className="mt-3">
                        <LemonMenu
                            items={[
                                {
                                    icon: STEP_TYPE_ICONS['element'],
                                    label: STEP_TYPE_LABELS['element']!,
                                    onClick: () => addStep('element'),
                                },
                                {
                                    icon: STEP_TYPE_ICONS['modal'],
                                    label: STEP_TYPE_LABELS['modal']!,
                                    onClick: () => addStep('modal'),
                                },
                                {
                                    icon: STEP_TYPE_ICONS['survey'],
                                    label: STEP_TYPE_LABELS['survey']!,
                                    onClick: () => addStep('survey'),
                                },
                            ]}
                            placement="bottom-start"
                            maxContentWidth
                        >
                            <LemonButton
                                type="secondary"
                                fullWidth
                                icon={<IconPlus />}
                                sideIcon={<IconChevronDown />}
                                disabledReason={isAddingStep ? 'Already adding step' : undefined}
                            >
                                Add step
                            </LemonButton>
                        </LemonMenu>
                    </div>
                </div>

                <div className="p-4 border-t border-border-bold-3000 bg-bg-light">
                    <LemonButton
                        type="tertiary"
                        size="small"
                        fullWidth
                        icon={<IconExternal />}
                        loading={pendingEditInPostHog}
                        onClick={saveAndEditInPostHog}
                    >
                        {userIntent === 'edit-product-tour' && window.opener
                            ? 'Save & close'
                            : 'Save & edit in PostHog'}
                    </LemonButton>
                </div>
            </div>

            {editorState.mode === 'selecting' && (
                <div
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        position: 'fixed',
                        left: '50%',
                        transform: 'translateX(-50%)',
                        top: 16,
                        display: 'flex',
                        alignItems: 'center',
                        gap: 12,
                        paddingLeft: 16,
                        paddingRight: 8,
                        paddingTop: 10,
                        paddingBottom: 10,
                        borderRadius: 999,
                        backgroundColor: 'var(--primary-3000)',
                        color: '#fff',
                        fontSize: 14,
                        fontWeight: 500,
                        boxShadow: '0 4px 12px rgba(29, 74, 255, 0.3)',
                        zIndex: 2147483020,
                        pointerEvents: 'auto',
                    }}
                >
                    <div className="flex items-center gap-2">
                        <span
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{
                                width: 8,
                                height: 8,
                                borderRadius: '50%',
                                backgroundColor: '#fff',
                                animation: 'pulse 2s infinite',
                            }}
                        />
                        <span>Click an element for step {editorState.stepIndex + 1}</span>
                    </div>
                    <button
                        type="button"
                        onClick={() => setEditorState({ mode: 'idle' })}
                        className="p-1.5 rounded-full border-none cursor-pointer flex items-center justify-center"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            background: 'rgba(255, 255, 255, 0.2)',
                            color: '#fff',
                        }}
                    >
                        <IconX className="w-4 h-4" />
                    </button>
                </div>
            )}

            <style>
                {`
                    @keyframes pulse {
                        0%, 100% { opacity: 1; }
                        50% { opacity: 0.5; }
                    }
                `}
            </style>
        </>
    )
}
