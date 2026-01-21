import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconCursorClick, IconEye, IconPlay, IconX } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { toolbarLogic } from '~/toolbar/bar/toolbarLogic'

import { getStepElement, productToursLogic, TourStep } from './productToursLogic'

/** PostHog brand blue - used for step indicators */
const POSTHOG_BLUE = '#1d4aff'

const BAR_HEIGHT = 56

function getStepTitle(step: TourStep, index: number): string {
    if (step.content?.content?.[0]?.content?.[0]?.text) {
        const text = step.content.content[0].content[0].text
        return text.length > 20 ? text.slice(0, 19) + '…' : text
    }
    return `Step ${index + 1}`
}

function getStepTypeLabel(step: TourStep): string {
    switch (step.type) {
        case 'element':
            return 'Element'
        case 'modal':
            return 'Modal'
        case 'survey':
            return 'Survey'
        case 'banner':
            return 'Banner'
        default:
            return 'Step'
    }
}

export function ProductToursEditingBar(): JSX.Element | null {
    const { theme } = useValues(toolbarLogic)
    const { selectedTour, selectedTourSteps, editorState, selectingStepIndex, stepCount, launchedForElementSelection } =
        useValues(productToursLogic)
    const { selectTour, previewTour, previewStep, startElementSelection, cancelSelection } =
        useActions(productToursLogic)

    const themeProps = { theme } as { theme?: string }

    useEffect(() => {
        if (selectedTour !== null) {
            document.body.style.marginTop = `${BAR_HEIGHT}px`
            return () => {
                document.body.style.marginTop = ''
            }
        }
    }, [selectedTour])

    if (selectedTour === null) {
        return null
    }

    const isSelecting = editorState.mode === 'selecting'

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
                    <span className="font-semibold text-sm truncate max-w-48">{selectedTour.name || 'Unnamed tour'}</span>
                    <span className="text-muted text-xs">({stepCount} steps)</span>
                </div>

                {/* Center: Step buttons */}
                <div className="flex-1 flex items-center justify-center gap-1.5 overflow-x-auto">
                    {selectedTourSteps.map((step: TourStep, index: number) => {
                        const isActive = selectingStepIndex === index
                        const title = getStepTitle(step, index)
                        const typeLabel = getStepTypeLabel(step)
                        const hasElement = step.type === 'element'
                        const elementFound = hasElement ? !!getStepElement(step) : true

                        return (
                            <div key={step.id || index} className="flex items-center">
                                {index > 0 && <span className="text-muted text-xs mx-0.5">→</span>}
                                <Tooltip
                                    title={
                                        <div className="text-xs">
                                            <div className="font-semibold">{title}</div>
                                            <div className="text-muted">{typeLabel}</div>
                                            {hasElement && !elementFound && (
                                                <div className="text-warning mt-1">Element not found on this page</div>
                                            )}
                                            {hasElement && <div className="mt-1">Click to re-select element</div>}
                                        </div>
                                    }
                                >
                                    <button
                                        type="button"
                                        onClick={() => {
                                            if (hasElement) {
                                                if (isActive) {
                                                    cancelSelection()
                                                } else {
                                                    previewStep(index)
                                                    startElementSelection(index)
                                                }
                                            } else {
                                                previewStep(index)
                                            }
                                        }}
                                        className={`
                                            flex items-center gap-1.5 px-2 py-1 rounded-md text-xs
                                            transition-all
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
                                        <span className="font-medium">{title}</span>
                                        {hasElement && (
                                            <IconCursorClick
                                                className={`w-3 h-3 ${elementFound ? 'text-success' : 'text-warning'}`}
                                            />
                                        )}
                                    </button>
                                </Tooltip>
                            </div>
                        )
                    })}

                    {stepCount === 0 && (
                        <span className="text-muted text-sm">No steps yet. Add steps in the PostHog app.</span>
                    )}
                </div>

                {/* Right: Actions */}
                <div className="flex items-center gap-2">
                    <LemonButton
                        size="small"
                        type="secondary"
                        icon={<IconPlay />}
                        onClick={previewTour}
                        disabledReason={stepCount === 0 ? 'Add steps first' : undefined}
                    >
                        Preview
                    </LemonButton>

                    <LemonButton
                        size="small"
                        type="secondary"
                        icon={<IconX />}
                        onClick={() => {
                            if (launchedForElementSelection) {
                                window.close()
                            } else {
                                selectTour(null)
                            }
                        }}
                    >
                        {launchedForElementSelection ? 'Close' : 'Done'}
                    </LemonButton>
                </div>
            </div>

            {/* Selection mode indicator */}
            {isSelecting && (
                <div
                    className="fixed left-1/2 -translate-x-1/2 flex items-center gap-2 px-3 py-2 rounded-full bg-[#1d4aff] text-white text-sm font-medium shadow-lg pointer-events-auto"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ zIndex: 2147483019, top: BAR_HEIGHT + 12 }}
                    {...themeProps}
                >
                    <IconCursorClick className="w-4 h-4" />
                    <span>Click to select element for step {(selectingStepIndex ?? 0) + 1}</span>
                    <button
                        type="button"
                        onClick={() => cancelSelection()}
                        className="ml-1 p-0.5 rounded-full hover:bg-white/20 transition-colors"
                    >
                        <IconX className="w-4 h-4" />
                    </button>
                </div>
            )}
        </>
    )
}
