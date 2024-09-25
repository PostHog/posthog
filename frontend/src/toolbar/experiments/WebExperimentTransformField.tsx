import { IconAIText, IconCode, IconMessage } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSegmentedButton, LemonSegmentedButtonOption } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { useState } from 'react'

import { experimentsTabLogic } from '~/toolbar/experiments/experimentsTabLogic'
import { WebExperimentTransform } from '~/toolbar/types'

interface WebExperimentTransformFieldProps {
    variant: string
    tIndex: number
    transform: WebExperimentTransform
}
type elementTransformKind = 'html' | 'text' | 'css'
const ELEMENT_TRANSFORM_OPTIONS: LemonSegmentedButtonOption<elementTransformKind>[] = [
    {
        value: 'html',
        label: 'HTML',
        icon: <IconCode />,
    },
    {
        value: 'text',
        label: 'Text',
        icon: <IconMessage />,
    },
    {
        value: 'css',
        label: 'CSS',
        icon: <IconAIText />,
    },
]

export function WebExperimentTransformField({
    variant,
    tIndex,
    transform,
}: WebExperimentTransformFieldProps): JSX.Element {
    const [transformSelected, setTransformSelected] = useState(transform.html ? 'html' : 'text')
    const { experimentForm, inspectingElement, selectedVariant } = useValues(experimentsTabLogic)
    const { setExperimentFormValue, selectVariant, inspectForElementWithIndex } = useActions(experimentsTabLogic)
    return (
        <>
            <div className="flex-1 mb-2">
                <LemonButton
                    size="small"
                    type={inspectingElement === tIndex && selectedVariant === variant ? 'primary' : 'secondary'}
                    onClick={(e) => {
                        e.stopPropagation()
                        selectVariant(variant)
                        inspectForElementWithIndex(variant, inspectingElement === tIndex ? null : tIndex)
                    }}
                >
                    {transform.selector ? 'Change element' : 'Select element'}
                </LemonButton>
            </div>
            <LemonSegmentedButton
                fullWidth
                options={ELEMENT_TRANSFORM_OPTIONS}
                onChange={(e) => {
                    setTransformSelected(e)
                    if (experimentForm.variants) {
                        const webVariant = experimentForm.variants[variant]
                        if (webVariant && transform.selector) {
                            const element = document.querySelector(transform.selector) as HTMLElement
                            switch (e) {
                                case 'html':
                                    if (transform.html === '') {
                                        transform.html = element.outerHTML
                                    }
                                    break

                                case 'text':
                                    if (transform.text === '' && element.textContent) {
                                        transform.text = element.textContent
                                    }
                                    break
                                case 'css':
                                    if (transform.css === '' && element.hasAttribute('style')) {
                                        transform.css = element.getAttribute('style')!
                                    }
                                    break
                            }
                            setExperimentFormValue('variants', experimentForm.variants)
                        }
                    }
                }}
                value={transformSelected}
            />
            {transformSelected == 'text' && (
                <LemonTextArea
                    onChange={(value) => {
                        if (experimentForm.variants) {
                            const webVariant = experimentForm.variants[variant]
                            if (webVariant && transform.selector) {
                                webVariant.transforms[tIndex].text = value
                                const element = document.querySelector(transform.selector) as HTMLElement
                                if (element) {
                                    element.innerText = value
                                }
                            }
                        }
                        setExperimentFormValue('variants', experimentForm.variants)
                    }}
                    value={transform.text}
                />
            )}

            {transformSelected == 'html' && (
                <LemonTextArea
                    onChange={(value) => {
                        transform.html = value
                        if (experimentForm.variants) {
                            const webVariant = experimentForm.variants[variant]
                            if (webVariant && transform.selector) {
                                webVariant.transforms[tIndex].html = value
                                const element = document.querySelector(transform.selector) as HTMLElement
                                if (element) {
                                    element.outerHTML = value
                                }
                            }
                        }
                        setExperimentFormValue('variants', experimentForm.variants)
                    }}
                    value={transform.html}
                />
            )}

            {transformSelected == 'css' && (
                <LemonTextArea
                    onChange={(value) => {
                        if (experimentForm.variants) {
                            const webVariant = experimentForm.variants[variant]
                            if (webVariant && transform.selector) {
                                webVariant.transforms[tIndex].css = value
                                const element = document.querySelector(transform.selector) as HTMLElement
                                element.setAttribute('style', value)
                            }
                        }
                        setExperimentFormValue('variants', experimentForm.variants)
                    }}
                    value={transform.css}
                />
            )}
        </>
    )
}
