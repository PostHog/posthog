import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import {
    WebExperimentEditor,
    WebExperimentEditorContext,
    canRenameVariant,
} from '~/toolbar/shared/experiments/webExperimentEditorContext'

import { extensionExperimentsLogic } from '../../logics/panel/extensionExperimentsLogic'

/** Binds the toolbar's web experiment editor components to the panel's copy of the form. The page applies the changes. */
export function ExtensionExperimentEditorProvider({ children }: { children: React.ReactNode }): JSX.Element | null {
    const { experimentsState, experimentForm } = useValues(extensionExperimentsLogic)
    const { sendExperimentsCommand, renameVariant, setTransformField } = useActions(extensionExperimentsLogic)

    const editor = useMemo((): WebExperimentEditor | null => {
        if (!experimentsState) {
            return null
        }
        return {
            variants: experimentForm.variants,
            selectedExperimentId: experimentsState.selectedExperimentId,
            selectedVariant: experimentsState.selectedVariant,
            selectedElementType: experimentsState.selectedElementType,
            inspectingElement: experimentsState.inspectingElement,
            removeVariantAvailable: experimentsState.removeVariantAvailable,
            renameVariant: (variant, newKey) => {
                if (!canRenameVariant(experimentForm.variants, variant, newKey)) {
                    return false
                }
                renameVariant(variant, newKey)
                return true
            },
            removeVariant: (variant) => sendExperimentsCommand({ type: 'remove-experiment-variant', variant }),
            addTransformation: (variant) => sendExperimentsCommand({ type: 'add-experiment-transform', variant }),
            removeTransformation: (variant, index) =>
                sendExperimentsCommand({ type: 'remove-experiment-transform', variant, index }),
            selectElementType: (elementType) =>
                sendExperimentsCommand({ type: 'set-experiment-element-type', elementType }),
            inspectForTransformation: (variant, index) =>
                sendExperimentsCommand({ type: 'inspect-for-experiment-transform', variant, index }),
            setTransformationField: setTransformField,
            setTransformationSelector: (variant, index, selector) =>
                sendExperimentsCommand({ type: 'set-experiment-transform-selector', variant, index, selector }),
        }
    }, [experimentsState, experimentForm.variants, sendExperimentsCommand, renameVariant, setTransformField])

    return editor ? (
        <WebExperimentEditorContext.Provider value={editor}>{children}</WebExperimentEditorContext.Provider>
    ) : null
}
