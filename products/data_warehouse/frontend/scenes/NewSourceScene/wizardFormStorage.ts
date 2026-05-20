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
        const key = storageKey(sourceKind)
        const saved = sessionStorage.getItem(key)
        if (saved) {
            sessionStorage.removeItem(key)
            return JSON.parse(saved) as Record<string, unknown>
        }
    } catch {
        // sessionStorage may be unavailable or data may be corrupted
    }
    return null
}
