const SESSION_STORAGE_KEY = 'sourceWizard_formState'

function storageKey(sourceKind: string): string {
    return `${SESSION_STORAGE_KEY}_${sourceKind}`
}

export function saveSourceFormState(sourceKind: string, formValues: Record<string, unknown>): void {
    try {
        sessionStorage.setItem(storageKey(sourceKind), JSON.stringify(formValues))
    } catch {
        // sessionStorage may be unavailable
    }
}

export function restoreSourceFormState(sourceKind: string): Record<string, unknown> | null {
    try {
        const saved = sessionStorage.getItem(storageKey(sourceKind))
        if (saved) {
            return JSON.parse(saved) as Record<string, unknown>
        }
    } catch {
        // sessionStorage may be unavailable or data may be corrupted
    }
    return null
}

// Keep the snapshot until the wizard finishes: reading it must not delete it, or a re-mount in
// the same visit restores an empty form. Clear it when the wizard is closed or cleared instead.
export function clearSourceFormState(sourceKind: string): void {
    try {
        sessionStorage.removeItem(storageKey(sourceKind))
    } catch {
        // sessionStorage may be unavailable
    }
}
