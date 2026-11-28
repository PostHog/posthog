// Pinned: the backend replaces this exact token with the replying person's first name.
export const SENDER_NAME_AUTHOR_PLACEHOLDER = '{author_first_name}'

export interface SenderNameTemplateSaveState {
    isSaving: boolean
    isSavingAny: boolean
    disabledReason: string | undefined
    description: string
}

export function senderNameTemplateSaveState({
    configId,
    value,
    savedValue,
    displayName,
    restrictionReason,
    savingConfigId,
}: {
    configId: string
    value: string
    savedValue: string
    displayName: string
    restrictionReason?: string | null
    savingConfigId: string | null
}): SenderNameTemplateSaveState {
    const trimmed = value.trim()
    const isSaving = savingConfigId === configId
    const isSavingAny = savingConfigId !== null
    const hasPlaceholder = trimmed.includes(SENDER_NAME_AUTHOR_PLACEHOLDER)
    const disabledReason =
        restrictionReason ??
        (trimmed && !hasPlaceholder
            ? `Include ${SENDER_NAME_AUTHOR_PLACEHOLDER}`
            : trimmed === savedValue
              ? 'No changes to save'
              : isSavingAny
                ? 'Saving a sender name'
                : undefined)
    const description = hasPlaceholder
        ? `A reply from Sam shows as "${trimmed.split(SENDER_NAME_AUTHOR_PLACEHOLDER).join('Sam')}". AI replies show as "${displayName}".`
        : `Use ${SENDER_NAME_AUTHOR_PLACEHOLDER} to show who replied, for example "${SENDER_NAME_AUTHOR_PLACEHOLDER} at Acme". Leave blank to show every reply as "${displayName}".`

    return { isSaving, isSavingAny, disabledReason, description }
}
