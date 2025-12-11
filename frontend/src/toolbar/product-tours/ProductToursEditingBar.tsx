import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconCheck, IconMagicWand, IconPlus, IconTrash, IconX } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { Spinner } from 'lib/lemon-ui/Spinner'

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

const BAR_HEIGHT = 56

export function ProductToursEditingBar(): JSX.Element | null {
    const { theme } = useValues(toolbarLogic)
    const { selectedTourId, tourForm, tourFormErrors, inspectingElement, aiGenerating, aiGenerationStep, stepCount } =
        useValues(productToursLogic)
    const { selectTour, editStep, removeStep, inspectForElementWithIndex, saveTour, generateWithAI, setTourFormValue } =
        useActions(productToursLogic)

    const themeProps = { theme } as { theme?: string }
    const steps = tourForm?.steps || []
    const generationStatus = GENERATION_STATUS[aiGenerationStep] || ''

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

    return (
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

            {/* Center: Step buttons (like Product Fruits) */}
            <div className="flex-1 flex items-center justify-center gap-1">
                {stepCount === 0 && (
                    <span className="text-muted text-sm">Click an element on the page to add a step</span>
                )}
                {steps.map((step: TourStep, index: number) => {
                    const isActive = inspectingElement === index
                    return (
                        <div key={step.id} className="flex items-center gap-1 toolbar-animate-blur-right">
                            {index > 0 && <span className="text-muted-alt">+</span>}
                            <LemonButton
                                size="small"
                                type={isActive ? 'primary' : 'secondary'}
                                onClick={() => {
                                    if (isActive) {
                                        inspectForElementWithIndex(null)
                                    } else {
                                        editStep(index)
                                    }
                                }}
                                sideAction={{
                                    icon: <IconTrash className="w-3 h-3" />,
                                    tooltip: 'Remove step',
                                    onClick: () => removeStep(index),
                                }}
                            >
                                Step #{index + 1}
                            </LemonButton>
                        </div>
                    )
                })}
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconPlus />}
                    onClick={() => inspectForElementWithIndex(steps.length)}
                    disabled={aiGenerating}
                />
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

                <LemonButton size="small" type="secondary" icon={<IconX />} onClick={() => selectTour(null)}>
                    Discard
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
    )
}
