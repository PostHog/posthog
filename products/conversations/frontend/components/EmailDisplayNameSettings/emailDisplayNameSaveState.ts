export interface EmailDisplayNameSaveState {
    isSaving: boolean
    isSavingAny: boolean
    disabledReason: string | undefined
}

export function emailDisplayNameSaveState({
    configId,
    value,
    savedValue,
    restrictionReason,
    savingConfigId,
}: {
    configId: string
    value: string
    savedValue: string
    restrictionReason?: string | null
    savingConfigId: string | null
}): EmailDisplayNameSaveState {
    const trimmed = value.trim()
    const isSaving = savingConfigId === configId
    const isSavingAny = savingConfigId !== null
    const disabledReason =
        restrictionReason ??
        (!trimmed
            ? 'Enter a display name'
            : trimmed === savedValue
              ? 'No changes to save'
              : isSavingAny
                ? 'Saving a display name'
                : undefined)

    return { isSaving, isSavingAny, disabledReason }
}
