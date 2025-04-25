import { actions, afterMount, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { forms } from 'kea-forms'

import { projectTreeLogic } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'

import type { saveUnderLogicType } from './saveUnderLogicType'

export interface SaveUnderLogicProps {
    type: string
    defaultFolder?: string
    objectRef?: string | null
    onSave?: (folder: string) => void
}

export const saveUnderLogic = kea<saveUnderLogicType>([
    path(['lib', 'components', 'SaveUnder', 'saveUnderLogic']),
    props({} as SaveUnderLogicProps),
    key((props) => props.type),
    connect(() => ({
        values: [projectTreeLogic, ['lastNewOperation']],
        actions: [projectTreeLogic, ['setLastNewOperation']],
    })),
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
            },
        ],
    }),
    listeners(({ actions, props }) => ({
        setLastNewOperation: ({ folder }) => {
            actions.setFormValue('folder', folder || props.defaultFolder || 'Unfiled')
        },
    })),
    forms(({ actions, values, props }) => ({
        form: {
            defaults: {
                folder: props.defaultFolder || 'Unfiled',
            },
            errors: ({ folder }) => ({
                folder: !folder ? 'You need to specify a folder.' : null,
            }),
            submit: (formValues) => {
                if (props.onSave) {
                    actions.setLastNewOperation(values.lastNewOperation?.objectType || 'unknown', formValues.folder)
                    props.onSave(formValues.folder || props.defaultFolder || 'Unfiled')
                }
            },
        },
    })),
    afterMount(({ actions, values }) => {
        if (values.lastNewOperation?.folder) {
            actions.setFormValue('folder', values.lastNewOperation.folder)
        }
    }),
])
