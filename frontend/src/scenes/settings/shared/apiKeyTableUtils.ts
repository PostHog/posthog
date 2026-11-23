import { LemonDialog } from '@posthog/lemon-ui'

export interface APIKeyTableRow {
    id: string
    label: string
    mask_value?: string | null
    scopes: string[]
    created_at: string
    created_by?: {
        email: string
        first_name?: string
        last_name?: string
    } | null
    last_used_at: string | null
    last_rolled_at: string | null
}

// "Jane D.": the last initial separates people who share a first name.
export function formatCreatedBy(user: NonNullable<APIKeyTableRow['created_by']>): string {
    const firstName = user.first_name?.trim()
    if (!firstName) {
        return user.email
    }
    const lastInitial = user.last_name?.trim().charAt(0)
    return lastInitial ? `${firstName} ${lastInitial.toUpperCase()}.` : firstName
}

export function openDeleteKeyDialog(
    key: Pick<APIKeyTableRow, 'id' | 'label'>,
    onDelete: (id: string) => void,
    description: string
): void {
    LemonDialog.open({
        title: `Permanently delete key "${key.label}"?`,
        description,
        primaryButton: {
            status: 'danger',
            children: 'Permanently delete',
            onClick: () => onDelete(key.id),
        },
    })
}
