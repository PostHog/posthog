import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { projectTreeLogic } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'

import type { saveToLogicType } from './saveToLogicType'

export interface SaveToLogicProps {
    onSaveTo?: (folder: string | null) => void
    defaultFolder?: string
}

export interface OpenSaveToProps {
    folder?: string | null
    defaultFolder?: string | null
    callback: (folder: string | null) => void
}

export const saveToLogic = kea<saveToLogicType>([
    path(['lib', 'components', 'SaveTo', 'saveToLogic']),
    props({} as SaveToLogicProps),
    connect(() => ({
        values: [projectTreeLogic, ['lastNewFolder'], featureFlagLogic, ['featureFlags']],
        actions: [projectTreeLogic, ['setLastNewFolder']],
    })),
    actions({
        openSaveTo: (props: OpenSaveToProps) => props,
        closeSaveTo: true,
    }),
    reducers({
        isOpen: [
            false,
            {
                openSaveTo: () => true,
                closeSaveTo: () => false,
            },
        ],
        callback: [
            null as null | ((folder: string | null) => void),
            {
                openSaveTo: (_, { callback }) => callback,
                closeSaveTo: () => null,
            },
        ],
    }),
    selectors({
        isFeatureEnabled: [(s) => [s.featureFlags], (featureFlags) => featureFlags[FEATURE_FLAGS.TREE_VIEW] ?? false],
    }),
    listeners(({ actions, values }) => ({
        setLastNewFolder: ({ folder }) => {
            actions.setFormValue('folder', folder)
        },
        openSaveTo: ({ folder, defaultFolder }) => {
            const realFolder = folder ?? values.lastNewFolder ?? defaultFolder ?? null
            if (!values.isFeatureEnabled) {
                values.callback?.(realFolder)
            } else {
                actions.setFormValue('folder', realFolder)
            }
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
                values.callback?.(formValues.folder ?? null)
                actions.closeSaveTo()
            },
        },
    })),
])
