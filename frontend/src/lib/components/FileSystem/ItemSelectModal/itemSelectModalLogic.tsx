import { actions, connect, kea, path, reducers } from 'kea'
import { forms } from 'kea-forms'

import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import type { itemSelectModalLogicType } from './itemSelectModalLogicType'

export const itemSelectModalLogic = kea<itemSelectModalLogicType>([
    path(['lib', 'components', 'FileSystem', 'ItemSelectModal', 'itemSelectModalLogic']),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
        actions: [projectTreeDataLogic, ['addShortcutItem']],
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
    forms(({ actions }) => ({
        form: {
            defaults: {
                item: null as TreeDataItem | null,
            },
            submit: (formValues) => {
                if (formValues.item?.record) {
                    actions.addShortcutItem(formValues.item.record as FileSystemEntry)
                }
                actions.closeItemSelectModal()
            },
        },
    })),
])
