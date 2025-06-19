import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { forms } from 'kea-forms'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'

import type { itemSelectModalLogicType } from './itemSelectModalLogicType'
import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'

export const itemSelectModalLogic = kea<itemSelectModalLogicType>([
    path(['lib', 'components', 'FileSystem', 'ItemSelectModal', 'itemSelectModalLogic']),
    connect(() => ({
        values: [
            projectTreeDataLogic,
            ['lastNewFolder', 'projectTreeRef', 'projectTreeRefEntry'],
            featureFlagLogic,
            ['featureFlags'],
        ],
        actions: [projectTreeDataLogic, ['setLastNewFolder', 'moveItem', 'addShortcutItem']],
    })),
    actions({
        openItemSelectModal: true,
        closeItemSelectModal: true,
    }),
    reducers({
        isOpen: [
            false,
            {
                openItemSelectModal: () => true,
                closeItemSelectModal: () => false,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        // openItemSelectModal: ({ items }) => {
        //     if (typeof values.lastNewFolder === 'string') {
        //         actions.setFormValue('folder', values.lastNewFolder)
        //     } else {
        //         const itemPath = items[0].path
        //         const itemFolder = joinPath(splitPath(itemPath).slice(0, -1))
        //         actions.setFormValue('folder', itemFolder)
        //     }
        // },
        closeItemSelectModal: () => {
            actions.closeItemSelectModal()
        },
    })),
    forms(({ actions }) => ({
        form: {
            defaults: {
                item: null as TreeDataItem | null,
            },
            errors: ({ item }) => ({
                item: item ? null : 'You need to specify an item.',
            }),
            submit: (formValues) => {
                actions.addShortcutItem(formValues.item)
                actions.closeItemSelectModal()
            },
        },
    })),
])
