import type { WidgetDateFromValue } from '../widget_types/widgetConfigShared'
import type { DashboardWidgetEditModalProps } from './registry'

type ValidationResult = { success: true } | { success: false; fieldErrors: Record<string, string> }

export type WidgetEditModalTileMetadataProps = Pick<
    DashboardWidgetEditModalProps,
    'name' | 'description' | 'defaultTitle'
>

export function getWidgetEditModalTileDefaults(props: Pick<DashboardWidgetEditModalProps, 'name' | 'description'>): {
    tileName: string
    tileDescription: string
} {
    return {
        tileName: props.name ?? '',
        tileDescription: props.description ?? '',
    }
}

export type WidgetTileMetadataPatch = {
    name?: string
    description?: string
}

export function buildWidgetTileMetadataPatch(
    props: WidgetEditModalTileMetadataProps,
    tileName: string,
    tileDescription: string
): WidgetTileMetadataPatch {
    const trimmedName = tileName.trim()
    const trimmedDescription = tileDescription.trim()
    const nameChanged = trimmedName !== (props.name ?? '').trim()
    const descriptionChanged = trimmedDescription !== (props.description ?? '').trim()

    const metadata: WidgetTileMetadataPatch = {}
    if (nameChanged) {
        metadata.name = trimmedName === (props.defaultTitle ?? 'Untitled').trim() ? '' : trimmedName
    }
    if (descriptionChanged) {
        metadata.description = trimmedDescription
    }
    return metadata
}

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
    setDateFrom: (dateFrom: WidgetDateFromValue) => ({ dateFrom }),
}

export const widgetEditModalListFieldReducers = {
    limit: [
        10,
        {
            setLimit: (_: number, { limit }: { limit: number }) => limit,
        },
    ],
    dateFrom: [
        '-7d' as WidgetDateFromValue,
        {
            setDateFrom: (_: WidgetDateFromValue, { dateFrom }: { dateFrom: WidgetDateFromValue }) => dateFrom,
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
            submit: (_state: boolean, _payload: { value: true }) => true,
            submitSuccess: (_state: boolean, _payload: { value: true }) => false,
            submitFailure: (_state: boolean, _payload: { value: true }) => false,
        },
    ],
}

export const widgetEditModalPropSelectors = {
    onClose: [(_: unknown, p: { onClose: () => void }) => [p.onClose], (onClose: () => void) => onClose],
    defaultTitle: [
        (_: unknown, p: { defaultTitle?: string }) => [p.defaultTitle],
        (defaultTitle?: string) => defaultTitle ?? 'Untitled',
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
