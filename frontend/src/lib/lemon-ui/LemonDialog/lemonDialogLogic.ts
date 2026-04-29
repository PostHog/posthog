import { kea, key, path, props } from 'kea'
import { forms } from 'kea-forms'

import type { lemonDialogLogicType } from './lemonDialogLogicType'

export type LemonDialogFormPropsType = {
    dialogId?: string
    errors?: Record<string, (value: string) => string | undefined>
}

export const lemonDialogLogic = kea<lemonDialogLogicType>([
    path((key) => ['components', 'lemon-dialog', 'lemonDialogLogic', key]),
    key((props) => props.dialogId || 'default'),
    props({} as LemonDialogFormPropsType),
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
