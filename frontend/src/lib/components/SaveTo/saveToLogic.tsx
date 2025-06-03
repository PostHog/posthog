import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

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

export const saveToLogic = kea<saveToLogicType>([
    path(['lib', 'components', 'SaveTo', 'saveToLogic']),
    props({} as SaveToLogicProps),
    connect(() => ({
        values: [projectTreeDataLogic, ['lastNewFolder'], featureFlagLogic, ['featureFlags']],
        actions: [projectTreeDataLogic, ['setLastNewFolder']],
    })),
    actions({
        openSaveToModal: (props: OpenSaveToProps) => props,
        closeSaveToModal: true,
        closedSaveToModal: true,
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
    }),
    selectors({
        isFeatureEnabled: [
            (s) => [s.featureFlags],
            (featureFlags) =>
                featureFlags[FEATURE_FLAGS.TREE_VIEW] || featureFlags[FEATURE_FLAGS.TREE_VIEW_RELEASE] || false,
        ],
    }),
    listeners(({ actions, values }) => ({
        setLastNewFolder: ({ folder }) => {
            actions.setFormValue('folder', folder)
        },
        openSaveToModal: ({ folder, defaultFolder }) => {
            const realFolder = folder ?? values.lastNewFolder ?? defaultFolder ?? null
            if (!values.isFeatureEnabled) {
                values.callback?.(realFolder ?? '')
            } else {
                actions.setFormValue('folder', realFolder)
            }
        },
        closeSaveToModal: () => {
            values.cancelCallback?.()
            actions.closedSaveToModal()
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
