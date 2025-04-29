import { actions, afterMount, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { forms } from 'kea-forms'

import { projectTreeLogic } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'

import type { saveToLogicType } from './saveToLogicType'

export interface SaveToLogicProps {
    type: string
    defaultFolder?: string | null
    objectRef?: string | null
    onSave?: (folder: string | null) => void
}

export const saveToLogic = kea<saveToLogicType>([
    path(['lib', 'components', 'SaveTo', 'saveToLogic']),
    props({} as SaveToLogicProps),
    key((props) => props.type),
    connect(() => ({
        values: [projectTreeLogic, ['lastNewFolder']],
        actions: [projectTreeLogic, ['setLastNewFolder']],
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
        setLastNewFolder: ({ folder }) => {
            actions.setFormValue('folder', folder || props.defaultFolder || null)
        },
    })),
    forms(({ actions, props }) => ({
        form: {
            defaults: {
                folder: props.defaultFolder ?? null,
            },
            errors: ({ folder }) => ({
                folder: !folder ? 'You need to specify a folder.' : null,
            }),
            submit: (formValues) => {
                if (props.onSave) {
                    actions.setLastNewFolder(formValues.folder)
                    props.onSave(formValues.folder ?? props.defaultFolder ?? null)
                    actions.closeModal()
                }
            },
        },
    })),
    afterMount(({ actions, values }) => {
        if (values.lastNewFolder !== null) {
            actions.setFormValue('folder', values.lastNewFolder)
        }
    }),
])
