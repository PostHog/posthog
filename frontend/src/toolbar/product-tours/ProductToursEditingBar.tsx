import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import {
    IconCheck,
    IconCursorClick,
    IconMagicWand,
    IconMessage,
    IconPlay,
    IconPlus,
    IconQuestion,
    IconTrash,
    IconX,
} from '@posthog/icons'
import { LemonButton, LemonInput, LemonMenu, Tooltip } from '@posthog/lemon-ui'

import { Spinner } from 'lib/lemon-ui/Spinner'
import { cn } from 'lib/utils/css-classes'

import { toolbarLogic } from '~/toolbar/bar/toolbarLogic'

import { TourStep, productToursLogic } from './productToursLogic'

const GENERATION_STATUS: Record<string, string> = {
    idle: '',
    capturing: 'Capturing page...',
    analyzing: 'Analyzing elements...',
    generating: 'Generating content...',
    done: '',
    error: '',
}

/** Get display title for a step */
function getStepTitle(step: TourStep, index: number): string {
    return step.content?.content?.[0]?.content?.[0]?.text || `Step ${index + 1}`
}

/** Check if step has content */
function stepHasContent(step: TourStep): boolean {
    return !!(step.content?.content && step.content.content.length > 0)
}

/** PostHog brand blue - used for step indicators */
const POSTHOG_BLUE = '#1d4aff'

const BAR_HEIGHT = 56

export function ProductToursEditingBar(): JSX.Element | null {
    const { theme } = useValues(toolbarLogic)
    const {
        selectedTourId,
        tourForm,
        tourFormErrors,
        editorState,
        editingStepIndex,
        aiGenerating,
        aiGenerationStep,
        stepCount,
    } = useValues(productToursLogic)
    const {
        selectTour,
        editStep,
        removeStep,
        saveTour,
        previewTour,
        generateWithAI,
        setTourFormValue,
        addStep,
        setEditorState,
        cancelEditing,
    } = useActions(productToursLogic)

    const themeProps = { theme } as { theme?: string }
    const steps = tourForm?.steps || []
    const generationStatus = GENERATION_STATUS[aiGenerationStep] || ''

    // Drag state for reordering
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

    useEffect(() => {
        if (selectedTourId !== null) {
            document.body.style.marginTop = `${BAR_HEIGHT}px`
            return () => {
                document.body.style.marginTop = ''
            }
        }
    }, [selectedTourId])

    if (selectedTourId === null) {
        return null
    }

    const isFreshTour = stepCount === 0 && editorState.mode === 'idle'

    return (
        <>
            <div
                className="fixed top-0 left-0 right-0 flex items-center gap-3 px-4 bg-bg-light border-b shadow-lg pointer-events-auto"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ zIndex: 2147483019, height: BAR_HEIGHT }}
                onClick={(e) => e.stopPropagation()}
                {...themeProps}
            >
                {/* Left: Tour name */}
                <div className="flex items-center gap-2">
                    <LemonInput
                        size="small"
                        placeholder="Tour name"
                        value={tourForm?.name || ''}
                        onChange={(value) => setTourFormValue('name', value)}
                        status={tourFormErrors?.name ? 'danger' : undefined}
                        className="w-48"
                    />
                </div>

                {/* Center: Step buttons with titles */}
                <div className="flex-1 flex items-center justify-center gap-1.5">
                    {steps.map((step: TourStep, index: number) => {
                        const isActive = editingStepIndex === index
                        const isDragging = dragIndex === index
                        const isDropTarget = dropIndex === index && dragIndex !== index
                        const hasContent = stepHasContent(step)
                        const title = getStepTitle(step, index)
                        const displayTitle = title.length > 15 ? title.slice(0, 14) + '…' : title

                        return (
                            <div
                                key={step.id}
                                className={`flex items-center toolbar-animate-blur-right transition-all ${
                                    isDragging ? 'opacity-50 scale-95' : ''
                                } ${isDropTarget ? 'translate-x-1' : ''}`}
                                draggable
                                onDragStart={() => handleDragStart(index)}
                                onDragOver={(e) => handleDragOver(e, index)}
                                onDragEnd={handleDragEnd}
                            >
                                {index > 0 && <span className="text-muted text-xs mx-0.5">→</span>}
                                <Tooltip title={title !== displayTitle ? title : undefined}>
                                    <button
                                        type="button"
                                        onClick={() => {
                                            if (isActive) {
                                                cancelEditing()
                                            } else {
                                                editStep(index)
                                            }
                                        }}
                                        className={`
                                        flex items-center gap-1.5 px-2 py-1 rounded-md text-xs
                                        cursor-grab active:cursor-grabbing transition-all
                                        ${
                                            isActive
                                                ? 'bg-primary text-white'
                                                : 'bg-bg-3000 hover:bg-border text-default'
                                        }
                                    `}
                                    >
                                        <span
                                            className="w-4 h-4 rounded-full flex items-center justify-center text-[10px] font-bold text-white shrink-0"
                                            // eslint-disable-next-line react/forbid-dom-props
                                            style={{ backgroundColor: POSTHOG_BLUE }}
                                        >
                                            {index + 1}
                                        </span>
                                        <span className="font-medium">{displayTitle}</span>
                                        {!hasContent && (
                                            <span className="w-1.5 h-1.5 rounded-full bg-warning shrink-0" />
                                        )}
                                    </button>
                                </Tooltip>
                                <button
                                    type="button"
                                    onClick={() => removeStep(index)}
                                    className="ml-0.5 w-5 h-5 rounded flex items-center justify-center text-muted hover:text-danger transition-colors opacity-60 hover:opacity-100"
                                    title="Remove step"
                                >
                                    <IconTrash className="w-3 h-3" />
                                </button>
                            </div>
                        )
                    })}
                    <LemonMenu
                        items={[
                            {
                                icon: <IconCursorClick />,
                                label: 'Element tooltip',
                                onClick: () => addStep('element'),
                            },
                            {
                                icon: <IconMessage />,
                                label: 'Pop-up',
                                onClick: () => addStep('modal'),
                            },
                            {
                                icon: <IconQuestion />,
                                label: 'Survey',
                                onClick: () => addStep('survey'),
                            },
                        ]}
                        placement="bottom"
                        className="min-w-48"
                    >
                        <button
                            type="button"
                            disabled={aiGenerating || editorState.mode !== 'idle'}
                            className={cn(
                                isFreshTour ? 'py-2 px-4' : 'w-6 h-6',
                                'cursor-pointer rounded-md border border-dashed border-border flex items-center justify-center text-muted hover:border-primary hover:text-primary transition-colors disabled:opacity-50 ml-1'
                            )}
                        >
                            {isFreshTour && (
                                <span className="text-muted text-sm mr-2">Click to start adding steps</span>
                            )}
                            <IconPlus className="w-3 h-3" />
                        </button>
                    </LemonMenu>
                </div>

                {/* Right: Actions */}
                <div className="flex items-center gap-2">
                    {aiGenerating ? (
                        <span className="flex items-center gap-2 text-primary text-sm px-3">
                            <Spinner className="w-4 h-4" />
                            {generationStatus}
                        </span>
                    ) : (
                        <LemonButton
                            size="small"
                            type="secondary"
                            icon={<IconMagicWand />}
                            onClick={generateWithAI}
                            disabledReason={stepCount === 0 ? 'Add at least one step first' : undefined}
                        >
                            Generate
                        </LemonButton>
                    )}

                    <LemonButton
                        size="small"
                        type="secondary"
                        icon={<IconPlay />}
                        onClick={previewTour}
                        disabledReason={
                            aiGenerating ? 'Wait for generation' : stepCount === 0 ? 'Add at least one step' : undefined
                        }
                    >
                        Preview
                    </LemonButton>

                    <LemonButton size="small" type="secondary" icon={<IconX />} onClick={() => selectTour(null)}>
                        Cancel
                    </LemonButton>

                    <LemonButton
                        size="small"
                        type="primary"
                        icon={<IconCheck />}
                        onClick={saveTour}
                        disabledReason={
                            aiGenerating
                                ? 'Wait for generation'
                                : stepCount === 0
                                  ? 'Add at least one step'
                                  : tourFormErrors?.name
                                    ? String(tourFormErrors.name)
                                    : !tourForm?.name
                                      ? 'Enter a tour name'
                                      : undefined
                        }
                    >
                        Save
                    </LemonButton>
                </div>
            </div>

            {/* Mode indicator - fixed below the bar */}
            {editorState.mode === 'selecting' && (
                <div
                    className="fixed left-1/2 -translate-x-1/2 flex items-center gap-2 px-3 py-2 rounded-full bg-[#1d4aff] text-white text-sm font-medium shadow-lg pointer-events-auto"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ zIndex: 2147483019, top: BAR_HEIGHT + 12 }}
                    {...themeProps}
                >
                    <IconCursorClick className="w-4 h-4" />
                    <span>
                        Click to {editorState.stepIndex < stepCount ? 'change' : 'select'} step{' '}
                        {editorState.stepIndex + 1}
                        {editorState.stepIndex < stepCount ? ' element' : ''}
                    </span>
                    <button
                        type="button"
                        onClick={() => setEditorState({ mode: 'idle' })}
                        className="ml-1 p-0.5 rounded-full hover:bg-white/20 transition-colors"
                    >
                        <IconX className="w-4 h-4" />
                    </button>
                </div>
            )}
        </>
    )
}
