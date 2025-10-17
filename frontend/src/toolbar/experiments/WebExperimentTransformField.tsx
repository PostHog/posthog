import { useActions, useValues } from 'kea'

import { IconCursorClick } from '@posthog/icons'
import { LemonLabel, LemonSelect } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'

import {
    ElementSelectorButtonTypes,
    ElementSelectorType,
    experimentsTabLogic,
} from '~/toolbar/experiments/experimentsTabLogic'
import { WebExperimentTransform } from '~/toolbar/types'

interface WebExperimentTransformFieldProps {
    variant: string
    transformIndex: number
    transform: WebExperimentTransform
}

export function WebExperimentTransformField({
    variant,
    transformIndex,
    transform,
}: WebExperimentTransformFieldProps): JSX.Element {
    const { experimentForm, inspectingElement, selectedVariant, selectedElementType } = useValues(experimentsTabLogic)
    const { setExperimentFormValue, selectVariant, selectElementType, inspectForElementWithIndex } =
        useActions(experimentsTabLogic)

    return (
        <>
            <div className="inline-flex deprecated-space-x-2">
                <LemonButton
                    icon={<IconCursorClick />}
                    size="small"
                    type={inspectingElement === transformIndex && selectedVariant === variant ? 'primary' : 'secondary'}
                    onClick={() => {
                        selectVariant(variant)
                        inspectForElementWithIndex(
                            variant,
                            selectedElementType as ElementSelectorType,
                            inspectingElement === transformIndex ? null : transformIndex
                        )
                    }}
                >
                    {inspectingElement === transformIndex && selectedVariant === variant
                        ? 'Selecting…'
                        : 'Select element'}
                </LemonButton>
                <LemonSelect
                    placeholder="Select element type"
                    value={selectedElementType}
                    options={Object.entries(ElementSelectorButtonTypes).map(([key, value]) => ({
                        label: value,
                        value: key,
                    }))}
                    onChange={(value) => {
                        selectElementType(value as ElementSelectorType)
                    }}
                />
            </div>
            {transform.selector && (
                <div>
                    <div className="mt-4">
                        <LemonLabel>Inner HTML</LemonLabel>
                        <LemonTextArea
                            onChange={(value) => {
                                // Update state
                                const updatedVariants = {
                                    ...experimentForm.variants,
                                    [variant]: {
                                        ...experimentForm.variants[variant],
                                        transforms: experimentForm.variants[variant].transforms.map((t, i) =>
                                            i === transformIndex ? { ...t, html: value } : t
                                        ),
                                    },
                                }
                                setExperimentFormValue('variants', updatedVariants)

                                // Update DOM
                                const element = transform.selector
                                    ? (document.querySelector(transform.selector) as HTMLElement)
                                    : null
                                if (element) {
                                    element.innerHTML = value
                                }
                            }}
                            value={transform.html}
                            maxRows={8}
                        />
                    </div>
                    <div className="mt-4">
                        <LemonLabel>CSS</LemonLabel>
                        <LemonTextArea
                            onChange={(value) => {
                                if (experimentForm.variants) {
                                    // Create new variants object with updated CSS
                                    const updatedVariants = {
                                        ...experimentForm.variants,
                                        [variant]: {
                                            ...experimentForm.variants[variant],
                                            transforms: experimentForm.variants[variant].transforms.map((t, i) =>
                                                i === transformIndex ? { ...t, css: value } : t
                                            ),
                                        },
                                    }
                                    setExperimentFormValue('variants', updatedVariants)

                                    // Update DOM
                                    const element = transform.selector
                                        ? (document.querySelector(transform.selector) as HTMLElement)
                                        : null
                                    if (element) {
                                        element.setAttribute('style', value)
                                    }
                                }
                            }}
                            value={transform.css || ''}
                            maxRows={8}
                        />
                    </div>
                </div>
            )}
        </>
    )
}
