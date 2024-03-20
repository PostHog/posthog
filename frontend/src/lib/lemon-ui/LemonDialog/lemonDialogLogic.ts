import { kea, path } from 'kea'
import { forms } from 'kea-forms'

import type { lemonDialogLogicType } from './lemonDialogLogicType'

export const lemonDialogLogic = kea<lemonDialogLogicType>([
    path(['components', 'lemon-dialog', 'lemonDialogLogic']),
    forms(({ actions }) => ({
        form: {
            // errors: ({ name }) => ({
            //     name: !name ? 'Please enter your name' : undefined,
            // }),
            // submit: async (_, breakpoint) => {
            //     await breakpoint(3000)
            //     actions.resetSimpleForm()
            // },
        },
    })),
])
