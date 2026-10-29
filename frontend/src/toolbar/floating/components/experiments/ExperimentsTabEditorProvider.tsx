import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { experimentsTabLogic } from '~/toolbar/shared/experiments/experimentsTabLogic'
import { setSanitizedHTML, setSanitizedStyle } from '~/toolbar/shared/experiments/sanitize'
import {
    WebExperimentEditor,
    WebExperimentEditorContext,
    canRenameVariant,
} from '~/toolbar/shared/experiments/webExperimentEditorContext'

/** Binds the web experiment editor components to the floating toolbar's experiment form. */
export function ExperimentsTabEditorProvider({ children }: { children: React.ReactNode }): JSX.Element {
    const {
        experimentForm,
        selectedExperimentId,
        selectedVariant,
        selectedElementType,
        inspectingElement,
        removeVariantAvailable,
    } = useValues(experimentsTabLogic)
    const {
        setExperimentFormValue,
        removeVariant,
        addNewTransformation,
        removeElement,
        selectElementType,
        selectVariant,
        inspectForElementWithIndex,
        inspectElementSelected,
    } = useActions(experimentsTabLogic)

    const editor = useMemo((): WebExperimentEditor => {
        const variants = experimentForm.variants ?? {}
        return {
            variants,
            selectedExperimentId,
            selectedVariant,
            selectedElementType,
            inspectingElement,
            removeVariantAvailable: !!removeVariantAvailable,
            renameVariant: (variant, newKey) => {
                if (!canRenameVariant(variants, variant, newKey)) {
                    return false
                }
                setExperimentFormValue(
                    'variants',
                    Object.fromEntries(
                        Object.entries(variants).map(([key, value]) => [key === variant ? newKey : key, value])
                    )
                )
                return true
            },
            removeVariant,
            addTransformation: addNewTransformation,
            removeTransformation: removeElement,
            selectElementType,
            inspectForTransformation: (variant, index) => {
                selectVariant(variant)
                inspectForElementWithIndex(variant, selectedElementType, index)
            },
            setTransformationField: (variant, index, field, value) => {
                const webVariant = variants[variant]
                if (!webVariant) {
                    return
                }
                setExperimentFormValue('variants', {
                    ...variants,
                    [variant]: {
                        ...webVariant,
                        transforms: webVariant.transforms.map((t, i) => (i === index ? { ...t, [field]: value } : t)),
                    },
                })
                const selector = webVariant.transforms[index]?.selector
                const element = selector ? (document.querySelector(selector) as HTMLElement | null) : null
                if (element) {
                    if (field === 'html') {
                        setSanitizedHTML(element, value)
                    } else {
                        setSanitizedStyle(element, value)
                    }
                }
            },
            setTransformationSelector: (variant, index, selector) => {
                const element = document.querySelector(selector)
                if (element) {
                    inspectElementSelected(element as HTMLElement, variant, index, selector)
                }
            },
        }
    }, [
        experimentForm.variants,
        selectedExperimentId,
        selectedVariant,
        selectedElementType,
        inspectingElement,
        removeVariantAvailable,
        setExperimentFormValue,
        removeVariant,
        addNewTransformation,
        removeElement,
        selectElementType,
        selectVariant,
        inspectForElementWithIndex,
        inspectElementSelected,
    ])

    return <WebExperimentEditorContext.Provider value={editor}>{children}</WebExperimentEditorContext.Provider>
}
