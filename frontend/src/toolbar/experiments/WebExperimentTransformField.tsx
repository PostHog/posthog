import { LemonLabel } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
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
    tIndex: number
    transform: WebExperimentTransform
}

export function WebExperimentTransformField({
    variant,
    tIndex,
    transform,
}: WebExperimentTransformFieldProps): JSX.Element {
    const { experimentForm, inspectingElement, selectedVariant, selectedElementType } = useValues(experimentsTabLogic)
    const { setExperimentFormValue, selectVariant, selectElementType, inspectForElementWithIndex } =
        useActions(experimentsTabLogic)

    return (
        <>
            <div className="flex-1 mb-2">
                <LemonButton
                    size="small"
                    type={inspectingElement === tIndex && selectedVariant === variant ? 'primary' : 'secondary'}
                    sideAction={{
                        dropdown: {
                            overlay: (
                                <>
                                    {Object.entries(ElementSelectorButtonTypes).map(([key, value]) => {
                                        return (
                                            <LemonButton
                                                key={'element-selector-' + key}
                                                fullWidth
                                                type={
                                                    inspectingElement === tIndex &&
                                                    selectedVariant === variant &&
                                                    selectedElementType === key
                                                        ? 'primary'
                                                        : 'tertiary'
                                                }
                                                onClick={(e) => {
                                                    e.stopPropagation()
                                                    selectVariant(variant)
                                                    selectElementType(key as ElementSelectorType)
                                                    inspectForElementWithIndex(
                                                        variant,
                                                        key as ElementSelectorType,
                                                        inspectingElement === tIndex ? null : tIndex
                                                    )
                                                }}
                                            >
                                                {value}
                                            </LemonButton>
                                        )
                                    })}
                                </>
                            ),
                            placement: 'bottom',
                            matchWidth: true,
                        },
                    }}
                >
                    {transform.selector ? 'Change element' : 'Select element'}
                </LemonButton>
            </div>
            <div className="mt-4">
                <LemonLabel>HTML</LemonLabel>
                <LemonTextArea
                    onChange={(value) => {
                        transform.html = value
                        if (experimentForm.variants) {
                            const webVariant = experimentForm.variants[variant]
                            if (webVariant && transform.selector) {
                                webVariant.transforms[tIndex].html = value
                                const element = document.querySelector(transform.selector) as HTMLElement
                                if (element) {
                                    element.innerHTML = value
                                }
                            }
                        }
                        setExperimentFormValue('variants', experimentForm.variants)
                    }}
                    value={transform.html}
                />
            </div>
        </>
    )
}
