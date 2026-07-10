import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

export const PROMPT_NAME_MAX_LENGTH = 255

export function validatePromptName(name: string | undefined): string | undefined {
    if (!name?.trim()) {
        return 'Name is required'
    }
    if (name.toLowerCase() === 'new') {
        return "'new' is a reserved name and cannot be used"
    }
    if (name.length > PROMPT_NAME_MAX_LENGTH) {
        return `Name must be ${PROMPT_NAME_MAX_LENGTH} characters or fewer`
    }
    if (!/^[a-zA-Z0-9_-]+$/.test(name)) {
        return 'Only letters, numbers, hyphens (-), and underscores (_) are allowed'
    }
    return undefined
}

export function validatePromptConfig(config: string | undefined): string | undefined {
    if (!config?.trim()) {
        return undefined
    }
    try {
        const parsed = JSON.parse(config)
        if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
            return 'Config must be a JSON object, e.g. {"model": "gpt-5", "temperature": 0.2}'
        }
    } catch {
        return 'Config must be valid JSON'
    }
    return undefined
}

/** Parse the config editor's text into the API payload value. Empty text means "no config" (null). */
export function parsePromptConfig(config: string | undefined): Record<string, any> | null {
    if (!config?.trim()) {
        return null
    }
    return JSON.parse(config)
}

/** Format a prompt's stored config for the JSON text editor. */
export function formatPromptConfig(config: Record<string, any> | null | undefined): string {
    return config ? JSON.stringify(config, null, 2) : ''
}

export function getApiErrorDetail(error: unknown): string | undefined {
    if (error !== null && typeof error === 'object' && 'detail' in error && typeof error.detail === 'string') {
        return error.detail
    }
    return undefined
}

export function openDiscardChangesDialog(onDiscard: () => void): void {
    LemonDialog.open({
        title: 'Discard changes?',
        description: 'Your unsaved edits will be lost.',
        primaryButton: {
            children: 'Discard',
            type: 'primary',
            status: 'danger',
            onClick: onDiscard,
        },
        secondaryButton: {
            children: 'Keep editing',
            type: 'secondary',
        },
    })
}

export function openArchivePromptDialog(onArchive: () => void): void {
    LemonDialog.open({
        title: 'Archive prompt?',
        description:
            'This archives every active version of the prompt. Any code fetching it by name will stop resolving it.',
        primaryButton: {
            children: 'Archive',
            type: 'primary',
            status: 'danger',
            onClick: onArchive,
        },
        secondaryButton: {
            children: 'Cancel',
            type: 'secondary',
        },
    })
}
