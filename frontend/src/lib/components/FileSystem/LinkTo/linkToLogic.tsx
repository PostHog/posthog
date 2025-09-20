import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { forms } from 'kea-forms'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { PROJECT_TREE_KEY } from '~/layout/panel-layout/ProjectTree/ProjectTree'
import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { projectTreeLogic } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { calculateMovePath, joinPath, splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import type { linkToLogicType } from './linkToLogicType'

export const linkToLogic = kea<linkToLogicType>([
    path(['lib', 'components', 'LinkTo', 'linkToLogic']),
    connect(() => ({
        values: [
            projectTreeDataLogic,
            ['lastNewFolder', 'projectTreeRef', 'projectTreeRefEntry'],
            featureFlagLogic,
            ['featureFlags'],
        ],
        actions: [projectTreeDataLogic, ['setLastNewFolder', 'linkItem']],
    })),
    actions({
        openLinkToModal: (items: FileSystemEntry[]) => ({ items }),
        closeLinkToModal: true,
        closedLinkToModal: true,
    }),
    reducers({
        linkingItems: [
            [] as FileSystemEntry[],
            {
                openLinkToModal: (_, { items }) => items,
                closeLinkToModal: () => [],
            },
        ],
        isOpen: [
            false,
            {
                openLinkToModal: (_, { items }) => items.length > 0,
                closedLinkToModal: () => false,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        setLastNewFolder: ({ folder }) => {
            actions.setFormValue('folder', folder)
        },
        openLinkToModal: ({ items }) => {
            if (typeof values.lastNewFolder === 'string') {
                actions.setFormValue('folder', values.lastNewFolder)
            } else {
                const itemPath = items[0].path
                const itemFolder = joinPath(splitPath(itemPath).slice(0, -1))
                actions.setFormValue('folder', itemFolder)
            }
        },
        closeLinkToModal: () => {
            actions.closedLinkToModal()
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
                    values.linkingItems.some((item) => item.id === values.projectTreeRefEntry?.id)
                        ? values.projectTreeRef
                        : null

                if (values.linkingItems.length > 0) {
                    for (const item of values.linkingItems) {
                        const { newPath, isValidMove } = calculateMovePath(item, formValues.folder || '')
                        if (isValidMove) {
                            actions.linkItem(item.path, newPath, false, PROJECT_TREE_KEY)
                        }
                    }
                }

                // Clear the moving items and close the modal
                if (movingCurrentRef) {
                    const logic = projectTreeLogic.findMounted({ key: PROJECT_TREE_KEY })
                    logic?.actions.assureVisibility(movingCurrentRef)
                }

                actions.setLastNewFolder(formValues.folder)
                actions.closedLinkToModal()
            },
        },
    })),
])
