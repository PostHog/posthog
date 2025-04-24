import { actions, kea, key, path, props, reducers } from 'kea'
import { forms } from 'kea-forms'

import type { saveUnderLogicType } from './saveUnderLogicType'

export interface SaveUnderLogicProps {
    type: string
    name: string
    folder: string
    objectRef?: string | null
    onSave?: (props: { name: string; folder: string }) => void
}

export const saveUnderLogic = kea<saveUnderLogicType>([
    path(['lib', 'components', 'SaveUnder', 'saveUnderLogic']),
    props({} as SaveUnderLogicProps),
    key((props) => `${props.type}-${props.folder}`),
    actions({
        openModal: true,
        closeModal: true,
    }),
    reducers({
        isOpen: [
            false,
            {
                openModal: () => true,
                closeModal: () => false,
                save: () => false,
            },
        ],
    }),
    forms(({ props }) => ({
        saveUnder: {
            defaults: {
                name: props.name || '',
                folder: props.folder || 'Unfiled',
            },
            errors: ({ name, folder }) => ({
                name: !name
                    ? 'You need to have a name.'
                    : name.length > 150
                    ? 'This name is too long. Please keep it under 151 characters.'
                    : null,
                folder: !folder ? 'You need to specify a folder.' : null,
            }),
            submit: (formValues) => {
                if (props.onSave) {
                    const name = formValues.name || props.name
                    const folder = formValues.folder || props.folder
                    props.onSave({ name, folder })
                }
            },
        },
    })),
])
