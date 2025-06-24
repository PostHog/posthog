import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { forms } from 'kea-forms'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { PROJECT_TREE_KEY } from '~/layout/panel-layout/ProjectTree/ProjectTree'
import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { projectTreeLogic } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { calculateMovePath, joinPath, splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import type { moveToLogicType } from './moveToLogicType'

export const moveToLogic = kea<moveToLogicType>([
    path(['lib', 'components', 'MoveTo', 'moveToLogic']),
    connect(() => ({
        values: [
            projectTreeDataLogic,
            ['lastNewFolder', 'projectTreeRef', 'projectTreeRefEntry'],
            featureFlagLogic,
            ['featureFlags'],
        ],
        actions: [projectTreeDataLogic, ['setLastNewFolder', 'moveItem']],
    })),
    actions({
        openMoveToModal: (items: FileSystemEntry[]) => ({ items }),
        closeMoveToModal: true,
        closedMoveToModal: true,
    }),
    reducers({
        movingItems: [
            [] as FileSystemEntry[],
            {
                openMoveToModal: (_, { items }) => items,
                closeMoveToModal: () => [],
            },
        ],
        isOpen: [
            false,
            {
                openMoveToModal: (_, { items }) => items.length > 0,
                closedMoveToModal: () => false,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        setLastNewFolder: ({ folder }) => {
            actions.setFormValue('folder', folder)
        },
        openMoveToModal: ({ items }) => {
            if (typeof values.lastNewFolder === 'string') {
                actions.setFormValue('folder', values.lastNewFolder)
            } else {
                const itemPath = items[0].path
                const itemFolder = joinPath(splitPath(itemPath).slice(0, -1))
                actions.setFormValue('folder', itemFolder)
            }
        },
        closeMoveToModal: () => {
            actions.closedMoveToModal()
        },
    })),
    forms(({ actions, values }) => ({
        form: {
            defaults: {
                folder: null as string | null,
            },
            errors: ({ folder }) => ({
                folder: typeof folder !== 'string' ? 'You need to specify a folder.' : null,
            }),
            submit: (formValues) => {
                // When moving the current item, remember its ref so that we could open the destination folder later on
                const movingCurrentRef =
                    values.projectTreeRefEntry?.id &&
                    values.movingItems.some((item) => item.id === values.projectTreeRefEntry?.id)
                        ? values.projectTreeRef
                        : null
                if (values.movingItems.length > 0) {
                    for (const item of values.movingItems) {
                        const { newPath, isValidMove } = calculateMovePath(item, formValues.folder || '')
                        if (isValidMove) {
                            actions.moveItem(item, newPath, false, PROJECT_TREE_KEY)
                        }
                    }
                }

                // Clear the moving items and close the modal
                if (movingCurrentRef) {
                    const logic = projectTreeLogic.findMounted({ key: PROJECT_TREE_KEY })
                    logic?.actions.assureVisibility(movingCurrentRef)
                }

                actions.setLastNewFolder(formValues.folder)
                actions.closedMoveToModal()
            },
        },
    })),
])
