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
