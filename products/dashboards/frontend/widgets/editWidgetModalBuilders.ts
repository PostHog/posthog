type ValidationResult = { success: true } | { success: false; fieldErrors: Record<string, string> }

export const widgetEditModalTileActions = {
    setTileName: (tileName: string) => ({ tileName }),
    setTileDescription: (tileDescription: string) => ({ tileDescription }),
}

export const widgetEditModalTileReducers = {
    tileName: [
        '',
        {
            setTileName: (_: string, { tileName }: { tileName: string }) => tileName,
        },
    ],
    tileDescription: [
        '',
        {
            setTileDescription: (_: string, { tileDescription }: { tileDescription: string }) => tileDescription,
        },
    ],
}

export const widgetEditModalListFieldActions = {
    setLimit: (limit: number) => ({ limit }),
    setDateFrom: (dateFrom: string) => ({ dateFrom }),
}

export const widgetEditModalListFieldReducers = {
    limit: [
        10,
        {
            setLimit: (_: number, { limit }: { limit: number }) => limit,
        },
    ],
    dateFrom: [
        '-7d',
        {
            setDateFrom: (_: string, { dateFrom }: { dateFrom: string }) => dateFrom,
        },
    ],
}

export const widgetEditModalFilterTestAccountsActions = {
    setFilterTestAccounts: (filterTestAccounts: boolean) => ({ filterTestAccounts }),
}

export const widgetEditModalFilterTestAccountsReducers = {
    filterTestAccounts: [
        false,
        {
            setFilterTestAccounts: (_: boolean, { filterTestAccounts }: { filterTestAccounts: boolean }) =>
                filterTestAccounts,
        },
    ],
}

export const widgetEditModalFieldErrorsActions = {
    setFieldErrors: (fieldErrors: Record<string, string>) => ({ fieldErrors }),
    clearFieldError: (field: string) => ({ field }),
}

export const widgetEditModalFieldErrorsReducers = {
    fieldErrors: [
        {} as Record<string, string>,
        {
            setFieldErrors: (_: Record<string, string>, { fieldErrors }: { fieldErrors: Record<string, string> }) =>
                fieldErrors,
            clearFieldError: (state: Record<string, string>, { field }: { field: string }) => {
                if (!state[field]) {
                    return state
                }
                const next = { ...state }
                delete next[field]
                return next
            },
        },
    ],
}

export const widgetEditModalSavingReducers = {
    saving: [
        false,
        {
            submit: () => true,
            submitSuccess: () => false,
            submitFailure: () => false,
        },
    ],
}

export const widgetEditModalPropSelectors = {
    onClose: [(_: unknown, p: { onClose: () => void }) => [p.onClose], (onClose: () => void) => onClose],
    defaultTitle: [
        (_: unknown, p: { defaultTitle?: string }) => [p.defaultTitle],
        (defaultTitle?: string) => defaultTitle ?? 'Untitled',
    ],
    onSaveMetadata: [
        (_: unknown, p: { onSaveMetadata?: unknown }) => [p.onSaveMetadata],
        (onSaveMetadata: unknown) => onSaveMetadata,
    ],
}

export const widgetEditModalValidationSelectors = {
    activeFieldErrors: [
        (s: { validation: ValidationResult; fieldErrors: Record<string, string> }) => [s.validation, s.fieldErrors],
        (validation: ValidationResult, fieldErrors: Record<string, string>): Record<string, string> => {
            if (!validation.success) {
                return { ...validation.fieldErrors, ...fieldErrors }
            }
            return fieldErrors
        },
    ],
    saveDisabledReason: [
        (s: { saving: boolean; validation: ValidationResult }) => [s.saving, s.validation],
        (saving: boolean, validation: ValidationResult): string | undefined => {
            if (saving) {
                return 'Saving…'
            }
            if (!validation.success) {
                return 'Fix validation errors to save'
            }
            return undefined
        },
    ],
}
