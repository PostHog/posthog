import { createContext, useContext } from 'react'

import type { WebExperimentUrlMatchType, WebExperimentVariant } from '~/toolbar/shared/types'
import type { ExperimentIdType } from '~/types'

import type { ElementSelectorType } from './elementSelectorTypes'

/**
 * What the web experiment editor components read and change. The floating toolbar binds it to
 * `experimentsTabLogic` in the page. The extension side panel binds it to the panel's copy of the form, and the page
 * applies the changes.
 */
export interface WebExperimentEditor {
    variants: Record<string, WebExperimentVariant>
    selectedExperimentId: ExperimentIdType | null
    selectedVariant: string
    selectedElementType: ElementSelectorType
    /** The transformation waiting for an element pick on the page. */
    inspectingElement: number | null
    removeVariantAvailable: boolean
    /** Returns false when the rename is rejected, for example because another variant has the key. */
    renameVariant: (variant: string, newKey: string) => boolean
    removeVariant: (variant: string) => void
    addTransformation: (variant: string) => void
    removeTransformation: (variant: string, index: number) => void
    selectElementType: (elementType: ElementSelectorType) => void
    /** Pass a null index to stop picking. */
    inspectForTransformation: (variant: string, index: number | null) => void
    setTransformationField: (variant: string, index: number, field: 'html' | 'css', value: string) => void
    setTransformationSelector: (variant: string, index: number, selector: string) => void
    /** An empty url lets the variant change every page. */
    setVariantUrlCondition: (variant: string, url: string, urlMatchType: WebExperimentUrlMatchType) => void
}

export function canRenameVariant(
    variants: Record<string, WebExperimentVariant>,
    variant: string,
    newKey: string
): boolean {
    return !!variants[variant] && !!newKey && newKey !== variant && !variants[newKey]
}

/** Returns null when the variant is gone, so a caller can leave the form alone. */
export function variantsWithUrlCondition(
    variants: Record<string, WebExperimentVariant>,
    variant: string,
    url: string,
    urlMatchType: WebExperimentUrlMatchType
): Record<string, WebExperimentVariant> | null {
    const webVariant = variants[variant]
    if (!webVariant) {
        return null
    }
    return {
        ...variants,
        [variant]: {
            ...webVariant,
            conditions: { ...webVariant.conditions, url: url || undefined, urlMatchType },
        },
    }
}

export const WebExperimentEditorContext = createContext<WebExperimentEditor | null>(null)

export function useWebExperimentEditor(): WebExperimentEditor {
    const editor = useContext(WebExperimentEditorContext)
    if (!editor) {
        throw new Error('The web experiment editor components need a WebExperimentEditorContext provider')
    }
    return editor
}
