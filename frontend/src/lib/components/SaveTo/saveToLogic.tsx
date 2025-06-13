import { actions, connect, kea, listeners, path, props, reducers } from 'kea'
import { forms } from 'kea-forms'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'

import type { saveToLogicType } from './saveToLogicType'

export interface SaveToLogicProps {
    onSaveTo?: (folder: string | null) => void
    defaultFolder?: string
}

export interface OpenSaveToProps {
    /** Folder to preselect. */
    folder?: string | null
    /** Folder to use if the default folder is missing */
    defaultFolder?: string | null
    /** Returns the folder when selected */
    callback: (folder: string) => void
    /** Triggered if the modal was closed */
    cancelCallback?: () => void
}

export type SelectedFolder = string

export const saveToLogic = kea<saveToLogicType>([
    path(['lib', 'components', 'SaveTo', 'saveToLogic']),
    props({} as SaveToLogicProps),
    connect(() => ({
        values: [projectTreeDataLogic, ['lastNewFolder']],
        actions: [projectTreeDataLogic, ['setLastNewFolder']],
    })),
    actions({
        openSaveToModal: (props: OpenSaveToProps) => props,
        closeSaveToModal: true,
        closedSaveToModal: true,
        addSelectedFolder: (folder: SelectedFolder) => ({ folder }),
        removeSelectedFolder: (folderValue: string) => ({ folderValue }),
        clearSelectedFolders: true,
        // Used for keeping track of the default folder set on openSaveToModal
        setDefaultFolder: (defaultFolder: string | null) => ({ defaultFolder }),
    }),
    reducers({
        isOpen: [
            false,
            {
                openSaveToModal: () => true,
                closedSaveToModal: () => false,
            },
        ],
        callback: [
            null as null | ((folder: string) => void),
            {
                openSaveToModal: (_, { callback }) => callback ?? null,
                closedSaveToModal: () => null,
            },
        ],
        cancelCallback: [
            null as null | (() => void),
            {
                openSaveToModal: (_, { cancelCallback }) => cancelCallback ?? null,
                closedSaveToModal: () => null,
            },
        ],
        selectedFolders: [
            [] as SelectedFolder[],
            { persist: true },
            {
                addSelectedFolder: (state, { folder }) => {
                    // Check if folder already exists to avoid duplicates
                    if (state.some((f) => f === folder)) {
                        return state
                    }
                    return [...state, folder]
                },
                removeSelectedFolder: (state, { folderValue }) => state.filter((folder) => folder !== folderValue),
                clearSelectedFolders: () => [],
            },
        ],
        defaultFolder: [
            null as string | null,
            {
                openSaveToModal: (_, { defaultFolder }) => defaultFolder ?? null,
                closedSaveToModal: () => null,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        setLastNewFolder: ({ folder }) => {
            actions.setFormValue('folder', folder)
        },
        openSaveToModal: ({ folder, defaultFolder }) => {
            const realFolder = folder ?? values.lastNewFolder ?? defaultFolder ?? null
            actions.setFormValue('folder', realFolder)
            actions.setDefaultFolder(defaultFolder ?? null)
        },
        closeSaveToModal: () => {
            values.cancelCallback?.()
            actions.closedSaveToModal()
            actions.setDefaultFolder(null)
        },
    })),
    forms(({ actions, values }) => ({
        form: {
            defaults: {
                folder: null as string | null,
            },
            errors: ({ folder }) => ({
                folder: !folder ? 'You need to specify a folder.' : null,
            }),
            submit: (formValues) => {
                actions.setLastNewFolder(formValues.folder)
                values.callback?.(formValues.folder ?? '')
                actions.closedSaveToModal()
            },
        },
    })),
])

export function openSaveToModal(props: OpenSaveToProps): void {
    const logic = saveToLogic.findMounted()
    if (logic) {
        logic.actions.openSaveToModal(props)
    } else {
        console.error('SaveToLogic not mounted as part of <GlobalModals />')
        props.callback?.(props.folder ?? props.defaultFolder ?? '')
    }
}

export async function asyncSaveToModal(
    props: Omit<OpenSaveToProps, 'callback' | 'cancelCallback'>
): Promise<string | null> {
    return new Promise((resolve) => {
        openSaveToModal({
            ...props,
            callback: (folder) => {
                resolve(folder)
            },
            cancelCallback: () => {
                resolve(null)
            },
        })
    })
}
