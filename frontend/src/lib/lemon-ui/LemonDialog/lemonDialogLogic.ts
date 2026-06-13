import { kea, key, path, props } from 'kea'
import { forms } from 'kea-forms'

import type { lemonDialogLogicType } from './lemonDialogLogicType'

export type LemonDialogFormPropsType = {
    errors?: Record<string, (value: string) => string | undefined>
    /** Unique id that isolates this dialog's form state from other open dialogs. */
    dialogId?: string
}

export const lemonDialogLogic = kea<lemonDialogLogicType>([
    props({} as LemonDialogFormPropsType),
    key(({ dialogId }) => dialogId ?? 'default'),
    path((k) => ['components', 'lemon-dialog', 'lemonDialogLogic', k]),
    forms(({ props }) => ({
        form: {
            defaults: {} as Record<string, string>,
            errors: (values: Record<string, string>) => {
                const entries = Object.entries(props.errors || []).map(([key, valueOf]) => {
                    const result = valueOf(values[key])
                    return [key, result]
                })
                return Object.fromEntries(entries)
            },
        },
    })),
])
