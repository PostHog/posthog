import { kea, path, props } from 'kea'
import { forms } from 'kea-forms'

import type { lemonDialogLogicType } from './lemonDialogLogicType'

export type LemonDialogFormPropsType = {
    errors?: Record<string, (value: string) => string | undefined>
}

export const lemonDialogLogic = kea<lemonDialogLogicType>([
    path(['components', 'lemon-dialog', 'lemonDialogLogic']),
    props({} as LemonDialogFormPropsType),
    forms(({ props }) => ({
        form: {
            defaults: {},
            errors: (values) => {
                const entries = Object.entries(props.errors || []).map(([key, valueOf]) => {
                    const result = valueOf(values[key])
                    return [key, result]
                })
                return Object.fromEntries(entries)
            },
        },
    })),
])
