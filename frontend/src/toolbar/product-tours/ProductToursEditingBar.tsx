import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconCheck, IconPlay, IconPlus, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonInput } from 'lib/lemon-ui/LemonInput'

import { toolbarLogic } from '~/toolbar/bar/toolbarLogic'

import { productToursLogic } from './productToursLogic'

const BAR_HEIGHT = 52

export function ProductToursEditingBar(): JSX.Element | null {
    const { theme } = useValues(toolbarLogic)
    const { selectedTourId, tourForm, inspectingElement, isEditingStep } = useValues(productToursLogic)
    const { selectTour, addStep, editStep, inspectForElementWithIndex, setTourFormValue } =
        useActions(productToursLogic)
    const themeProps = { theme } as { theme?: string }

    // Push page content down when bar is visible
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

    const steps = tourForm?.steps || []
    const stepCount = steps.length

    let statusText: string
    if (isEditingStep) {
        statusText = 'Fill in the step details'
    } else if (inspectingElement !== null) {
        statusText = 'Click an element on the page'
    } else if (stepCount === 0) {
        statusText = 'Add steps to build your tour'
    } else {
        statusText = `${stepCount} step${stepCount === 1 ? '' : 's'}`
    }

    return (
        <div
            className="fixed top-0 left-0 right-0 flex items-center gap-3 px-4 bg-bg-light border-b shadow-md text-sm pointer-events-auto"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ zIndex: 2147483019, height: BAR_HEIGHT }}
            onClick={(e) => e.stopPropagation()}
            {...themeProps}
        >
            <LemonInput
                placeholder="Tour name..."
                value={tourForm?.name ?? ''}
                onChange={(value) => setTourFormValue('name', value)}
                className="w-48"
                size="small"
            />

            <div className="border-l h-6" />

            <div className="flex items-center gap-2">
                <span className="text-muted text-xs">{statusText}</span>
                {stepCount > 0 && (
                    <div className="flex items-center gap-1">
                        {steps.map((_, index) => (
                            <button
                                key={index}
                                type="button"
                                onClick={() =>
                                    inspectingElement === index ? inspectForElementWithIndex(null) : editStep(index)
                                }
                                className={`w-6 h-6 rounded-full text-xs font-medium transition-colors ${
                                    inspectingElement === index
                                        ? 'bg-primary text-primary-inverse'
                                        : 'bg-border hover:bg-border-bold text-default'
                                }`}
                                title={`Step ${index + 1}`}
                            >
                                {index + 1}
                            </button>
                        ))}
                    </div>
                )}
            </div>

            <div className="flex-1" />

            <div className="flex items-center gap-1">
                {inspectingElement !== null ? (
                    <LemonButton size="small" type="secondary" onClick={() => inspectForElementWithIndex(null)}>
                        Cancel
                    </LemonButton>
                ) : (
                    <LemonButton size="small" type="secondary" icon={<IconPlus />} onClick={() => addStep()}>
                        Add step
                    </LemonButton>
                )}

                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconX />}
                    onClick={() => {
                        // TODO: this should probably be a "delete" w/ confirmation
                        // if it's a pre-existing tour
                    }}
                    tooltip="Discard tour"
                />

                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconPlay />}
                    onClick={() => {
                        // TODO: make this do something...
                        // probably pending SDK changes
                    }}
                    tooltip="Preview tour"
                />

                <LemonButton
                    size="small"
                    type="primary"
                    icon={<IconCheck />}
                    onClick={() => {
                        // TODO: actually save the tour
                        selectTour(null)
                    }}
                    disabledReason={
                        !tourForm?.name ? 'Name your tour first' : stepCount === 0 ? 'Add at least one step' : undefined
                    }
                >
                    Save
                </LemonButton>
            </div>
        </div>
    )
}
