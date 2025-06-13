import { PreservableLogicConfig, statePreservationManager } from './statePreservationManager'

/**
 * Helper function to make a kea logic preservable.
 * Add this to your logic's afterMount and beforeUnmount sections.
 *
 * @param config - Configuration for state preservation
 * @returns An object with mount and unmount functions to add to your logic
 */
export function preservableLogic(config: Omit<PreservableLogicConfig, 'logic'>): {
    afterMount: ({ logic }: { logic: any }) => void
    beforeUnmount: () => void
} {
    return {
        afterMount: ({ logic }: { logic: any }) => {
            statePreservationManager.registerPreservableLogic({
                ...config,
                logic,
            })
        },
        beforeUnmount: () => {
            statePreservationManager.unregisterPreservableLogic(config.logicKey)
        },
    }
}

/**
 * Simplified version for basic form logics - automatically detects form fields
 */
export function preservableFormLogic(
    logicKey: string,
    options: {
        preserveKeys?: string[]
        restoreCallback?: (data: Record<string, any>) => void
    } = {}
): {
    afterMount: ({ logic }: { logic: any }) => void
    beforeUnmount: () => void
} {
    return preservableLogic({
        logicKey,
        preserveKeys: options.preserveKeys,
        restoreCallback: options.restoreCallback,
    })
}

/**
 * For kea-forms integration - automatically handles form state
 */
export function preservableKeaFormLogic(
    logicKey: string,
    formKey: string,
    options: {
        restoreCallback?: (data: Record<string, any>) => void
    } = {}
): {
    afterMount: ({ logic }: { logic: any }) => void
    beforeUnmount: () => void
} {
    return preservableLogic({
        logicKey,
        customExtractor: function (this: any): Record<string, any> {
            const logic = this.logic?.findMounted?.() || this.logic
            return logic?.values?.[formKey] || {}
        },
        customRestorer: function (this: any, data: Record<string, any>): void {
            const logic = this.logic?.findMounted?.() || this.logic
            const setterName = `set${formKey.charAt(0).toUpperCase() + formKey.slice(1)}Values`
            if (logic?.actions?.[setterName]) {
                logic.actions[setterName](data)
            }
        },
        restoreCallback: options.restoreCallback,
    })
}
