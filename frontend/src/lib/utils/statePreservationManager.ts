import { lemonToast } from '@posthog/lemon-ui'

export interface PreservedState {
    logicKey: string
    formData: Record<string, any>
    timestamp: number
    url: string
    expiresAt: number
}

export interface PreservableLogicConfig {
    logicKey: string
    logic: any
    preserveKeys?: string[] // specific keys to preserve, if not provided will try to preserve form-like data
    restoreCallback?: (data: Record<string, any>) => void
    customExtractor?: () => Record<string, any>
    customRestorer?: (data: Record<string, any>) => void
}

const EXPIRATION_MINUTES = 30
const STORAGE_KEY_PREFIX = 'posthog_preserved_logic_'

class StatePreservationManager {
    private preservableLogics: Map<string, PreservableLogicConfig> = new Map()
    private isAuthenticationInProgress = false

    registerPreservableLogic(config: PreservableLogicConfig): void {
        this.preservableLogics.set(config.logicKey, config)
    }

    unregisterPreservableLogic(logicKey: string): void {
        this.preservableLogics.delete(logicKey)
    }

    onAuthenticationChallenge(): void {
        if (this.isAuthenticationInProgress) {
            return
        }

        this.isAuthenticationInProgress = true
        this.preserveAllStates()
    }

    onAuthenticationComplete(): void {
        if (!this.isAuthenticationInProgress) {
            return
        }

        this.isAuthenticationInProgress = false
        // Small delay to let the page settle after auth redirect
        setTimeout(() => {
            this.restoreAllStates()
        }, 100)
    }

    onAuthenticationDismissed(): void {
        this.isAuthenticationInProgress = false
        // Don't auto-restore on dismissal, but keep the preserved state for manual restoration
    }

    private preserveAllStates(): void {
        this.preservableLogics.forEach((config, logicKey) => {
            try {
                const mountedLogic = config.logic.findMounted?.()
                if (!mountedLogic) {
                    return
                }

                const formData = this.extractFormData(config, mountedLogic)
                if (formData && Object.keys(formData).length > 0) {
                    this.saveState(logicKey, formData)
                }
            } catch (error) {
                console.warn(`Failed to preserve state for ${logicKey}:`, error)
            }
        })
    }

    private restoreAllStates(): void {
        const restoredLogics: string[] = []

        this.preservableLogics.forEach((config, logicKey) => {
            try {
                const preservedState = this.getPreservedState(logicKey)
                if (!preservedState) {
                    return
                }

                const mountedLogic = config.logic.findMounted?.()
                if (!mountedLogic) {
                    return
                }

                this.restoreFormData(config, mountedLogic, preservedState.formData)
                restoredLogics.push(logicKey)

                // Call custom restore callback if provided
                config.restoreCallback?.(preservedState.formData)
            } catch (error) {
                console.warn(`Failed to restore state for ${logicKey}:`, error)
            }
        })

        if (restoredLogics.length > 0) {
            lemonToast.info(`Restored unsaved changes from before authentication`, {
                button: {
                    label: 'Clear all',
                    action: () => {
                        this.clearAllPreservedStates()
                    },
                },
            })
        }
    }

    private extractFormData(config: PreservableLogicConfig, mountedLogic: any): Record<string, any> {
        if (config.customExtractor) {
            return config.customExtractor()
        }

        const values = mountedLogic.values || {}
        const formData: Record<string, any> = {}

        if (config.preserveKeys) {
            // Use specified keys
            config.preserveKeys.forEach((key) => {
                if (values[key] !== undefined) {
                    formData[key] = values[key]
                }
            })
        } else {
            // Auto-detect form-like data
            Object.keys(values).forEach((key) => {
                const value = values[key]

                // Skip certain types of values that shouldn't be preserved
                if (this.shouldPreserveValue(key, value)) {
                    formData[key] = value
                }
            })
        }

        return formData
    }

    private shouldPreserveValue(key: string, value: any): boolean {
        // Skip loading states, error states, etc.
        if (key.includes('Loading') || key.includes('Error') || key.includes('Success')) {
            return false
        }

        // Skip functions, null, undefined
        if (typeof value === 'function' || value === null || value === undefined) {
            return false
        }

        // Skip empty objects/arrays
        if (typeof value === 'object' && Object.keys(value).length === 0) {
            return false
        }

        // Skip boolean flags that are likely UI state
        if (typeof value === 'boolean' && (key.includes('show') || key.includes('is') || key.includes('has'))) {
            return false
        }

        return true
    }

    private restoreFormData(config: PreservableLogicConfig, mountedLogic: any, formData: Record<string, any>): void {
        if (config.customRestorer) {
            config.customRestorer(formData)
            return
        }

        const actions = mountedLogic.actions || {}

        // Try to restore form data using common kea-forms patterns
        Object.keys(formData).forEach((key) => {
            const value = formData[key]

            // Try direct setter (setFieldName)
            const setterName = `set${key.charAt(0).toUpperCase() + key.slice(1)}`
            if (actions[setterName]) {
                actions[setterName](value)
                return
            }

            // Try form field setter (setFormFieldName)
            const formSetterName = `setForm${key.charAt(0).toUpperCase() + key.slice(1)}`
            if (actions[formSetterName]) {
                actions[formSetterName](value)
                return
            }

            // Try kea-forms bulk setter pattern
            const formKeys = Object.keys(mountedLogic.values || {}).filter((k) => k.endsWith('Form'))
            formKeys.forEach((formKey) => {
                const formName = formKey.replace('Form', '')
                const bulkSetterName = `set${formName.charAt(0).toUpperCase() + formName.slice(1)}Values`
                if (actions[bulkSetterName]) {
                    actions[bulkSetterName]({ [key]: value })
                }
            })
        })
    }

    private saveState(logicKey: string, formData: Record<string, any>): void {
        try {
            const preservedState: PreservedState = {
                logicKey,
                formData,
                timestamp: Date.now(),
                url: window.location.href,
                expiresAt: Date.now() + EXPIRATION_MINUTES * 60 * 1000,
            }

            localStorage.setItem(`${STORAGE_KEY_PREFIX}${logicKey}`, JSON.stringify(preservedState))
        } catch (error) {
            console.warn(`Failed to save state for ${logicKey}:`, error)
        }
    }

    private getPreservedState(logicKey: string): PreservedState | null {
        try {
            const stored = localStorage.getItem(`${STORAGE_KEY_PREFIX}${logicKey}`)
            if (!stored) {
                return null
            }

            const parsed: PreservedState = JSON.parse(stored)

            if (Date.now() > parsed.expiresAt) {
                localStorage.removeItem(`${STORAGE_KEY_PREFIX}${logicKey}`)
                return null
            }

            return parsed
        } catch (error) {
            console.warn(`Failed to get preserved state for ${logicKey}:`, error)
            localStorage.removeItem(`${STORAGE_KEY_PREFIX}${logicKey}`)
            return null
        }
    }

    private clearAllPreservedStates(): void {
        this.preservableLogics.forEach((_, logicKey) => {
            localStorage.removeItem(`${STORAGE_KEY_PREFIX}${logicKey}`)
        })
    }

    // Cleanup expired states periodically
    cleanupExpiredStates(): void {
        const keys = Object.keys(localStorage).filter((key) => key.startsWith(STORAGE_KEY_PREFIX))

        keys.forEach((key) => {
            try {
                const stored = localStorage.getItem(key)
                if (stored) {
                    const parsed: PreservedState = JSON.parse(stored)
                    if (Date.now() > parsed.expiresAt) {
                        localStorage.removeItem(key)
                    }
                }
            } catch (error) {
                localStorage.removeItem(key)
            }
        })
    }
}

export const statePreservationManager = new StatePreservationManager()

// Helper function to easily register a logic as preservable
export function makeLogicPreservable(config: PreservableLogicConfig): void {
    statePreservationManager.registerPreservableLogic(config)
}

// Cleanup expired states on app load
if (typeof window !== 'undefined') {
    statePreservationManager.cleanupExpiredStates()
}
