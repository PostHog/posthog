import { actions, connect, kea, listeners, path, props, reducers } from 'kea'
import { forms } from 'kea-forms'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { PROJECT_TREE_KEY } from '~/layout/panel-layout/ProjectTree/ProjectTree'
import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { projectTreeLogic } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { calculateMovePath } from '~/layout/panel-layout/ProjectTree/utils'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import type { moveToLogicType } from './moveToLogicType'

export interface MoveToLogicProps {
    onMoveTo?: (folder: string | null) => void
    defaultFolder?: string
}

export const moveToLogic = kea<moveToLogicType>([
    path(['lib', 'components', 'MoveTo', 'moveToLogic']),
    props({} as MoveToLogicProps),
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
    listeners(({ actions }) => ({
        setLastNewFolder: ({ folder }) => {
            actions.setFormValue('folder', folder)
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
                folder: !folder ? 'You need to specify a folder.' : null,
            }),
            submit: (formValues) => {
                // When moving the current item, remember its ref so that we could open the destination folder later on
                const movingCurrentRef = values.movingItems.some((item) => item === values.projectTreeRefEntry)
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
                    projectTreeLogic.findMounted({ key: PROJECT_TREE_KEY })?.actions.assureVisibility(movingCurrentRef)
                }

                actions.setLastNewFolder(formValues.folder)
                actions.closedMoveToModal()
            },
        },
    })),
])
