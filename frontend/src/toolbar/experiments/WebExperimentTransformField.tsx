import { IconCode, IconMessage, IconPencil } from '@posthog/icons'
import { LemonDivider, LemonInput, LemonLabel } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { useState } from 'react'

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

    const [editSelectorShowing, setEditSelectorShowing] = useState(false)

    const selectedContentType = transform.html ? 'html' : 'text'
    return (
        <>
            <div className="flex-1 mb-2">
                <LemonButton
                    size="small"
                    type={inspectingElement === transformIndex && selectedVariant === variant ? 'primary' : 'secondary'}
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
                                                    inspectingElement === transformIndex &&
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
                                                        inspectingElement === transformIndex ? null : transformIndex
                                                    )
                                                }}
                                            >
                                                {value}
                                            </LemonButton>
                                        )
                                    })}
                                    <LemonDivider className="my-1" />
                                    <LemonButton
                                        fullWidth
                                        type="tertiary"
                                        icon={<IconPencil />}
                                        onClick={() => {
                                            setEditSelectorShowing(true)
                                        }}
                                    >
                                        Edit selector
                                    </LemonButton>
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
            {editSelectorShowing && (
                <div className="mb-2">
                    <LemonInput
                        value={transform.selector}
                        onChange={(value) => {
                            if (experimentForm.variants) {
                                const variants = { ...experimentForm.variants }
                                variants[variant].transforms[transformIndex].selector = value
                                setExperimentFormValue('variants', variants)
                            }
                        }}
                        placeholder="HTML element selector"
                    />
                </div>
            )}
            {transform.selector && (
                <div>
                    <div className="mt-4">
                        <LemonLabel>Content</LemonLabel>
                        <LemonSegmentedButton
                            className="mb-1"
                            fullWidth
                            options={[
                                {
                                    value: 'text',
                                    label: 'Text',
                                    icon: <IconMessage />,
                                },
                                {
                                    value: 'html',
                                    label: 'HTML',
                                    icon: <IconCode />,
                                },
                            ]}
                            onChange={(newSelectedContentType) => {
                                const variantConfig = experimentForm.variants[variant]
                                if (variantConfig && transform.selector) {
                                    // Before changing the content type, restore the original html state for this selector
                                    const originalHtmlState = experimentForm.original_html_state?.[transform.selector]
                                    if (originalHtmlState) {
                                        const element = document.querySelector(transform.selector) as HTMLElement
                                        if (element) {
                                            element.innerHTML = originalHtmlState.innerHTML
                                            element.textContent = originalHtmlState.textContent
                                        }
                                    }

                                    // Copy the original html state to the new transform, and delete the previously selected content type
                                    const element = document.querySelector(transform.selector) as HTMLElement
                                    if (element) {
                                        const newTransform = { ...transform }

                                        if (newSelectedContentType === 'html') {
                                            newTransform.html =
                                                experimentForm.original_html_state?.[transform.selector]?.innerHTML
                                            delete newTransform.text
                                        }
                                        if (newSelectedContentType === 'text' && element.textContent) {
                                            newTransform.text =
                                                experimentForm.original_html_state?.[transform.selector]?.textContent
                                            delete newTransform.html
                                        }

                                        const updatedVariants = {
                                            ...experimentForm.variants,
                                            [variant]: {
                                                ...variantConfig,
                                                transforms: variantConfig.transforms.map((t, i) =>
                                                    i === transformIndex ? newTransform : t
                                                ),
                                            },
                                        }
                                        setExperimentFormValue('variants', updatedVariants)
                                    }
                                }
                            }}
                            value={selectedContentType}
                        />
                        {selectedContentType == 'text' && (
                            <LemonTextArea
                                onChange={(value) => {
                                    // Update state
                                    const updatedVariants = {
                                        ...experimentForm.variants,
                                        [variant]: {
                                            ...experimentForm.variants[variant],
                                            transforms: experimentForm.variants[variant].transforms.map((t, i) =>
                                                i === transformIndex ? { ...t, text: value } : t
                                            ),
                                        },
                                    }
                                    setExperimentFormValue('variants', updatedVariants)

                                    // Update DOM
                                    const element = transform.selector
                                        ? (document.querySelector(transform.selector) as HTMLElement)
                                        : null
                                    if (element) {
                                        element.innerText = value
                                    }
                                }}
                                value={transform.text}
                            />
                        )}
                        {selectedContentType == 'html' && (
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
                            />
                        )}
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
                        />
                    </div>
                </div>
            )}
        </>
    )
}
