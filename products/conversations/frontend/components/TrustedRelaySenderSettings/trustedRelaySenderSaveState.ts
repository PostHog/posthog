export interface TrustedRelaySenderSaveState {
    isSaving: boolean
    isSavingAny: boolean
    disabledReason: string | undefined
}

export function trustedRelaySenderSaveState({
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
}): TrustedRelaySenderSaveState {
    const isDirty = value.trim().toLowerCase() !== savedValue
    const isSaving = savingConfigId === configId
    const isSavingAny = savingConfigId !== null
    const disabledReason =
        restrictionReason ??
        (!isDirty ? 'No changes to save' : isSavingAny ? 'Saving a trusted relay sender' : undefined)

    return { isSaving, isSavingAny, disabledReason }
}
