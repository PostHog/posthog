import { useActions, useValues } from 'kea'

import { IconNotebook, IconPlusSmall } from '@posthog/icons'
import type { ActionMenuItem } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import {
    NotebookSelectButtonLogicProps,
    notebookSelectButtonLogic,
} from 'scenes/notebooks/NotebookSelectButton/notebookSelectButtonLogic'
import { NotebookListItemType, NotebookTarget } from 'scenes/notebooks/types'

import type { SceneAction, SceneActionGroup } from '~/layout/scenes/sceneActions/sceneActionModel'
import { notebooksModel, openNotebook } from '~/models/notebooksModel'

interface AddToNotebookActionOptions {
    notebookSelectButtonProps?: NotebookSelectButtonLogicProps
    newNotebookTitle?: string
    group?: SceneActionGroup
    section?: string
}

/**
 * The "Add to notebook" submenu: new notebook, scratchpad, then the notebooks holding this resource and the others.
 * The notebook lists load when the submenu opens, not when the scene mounts. They stay out of the search, so they
 * never bury the scene's own rows.
 */
export function useAddToNotebookAction(
    dataAttrKey: string,
    { notebookSelectButtonProps, newNotebookTitle, group = 'file', section }: AddToNotebookActionOptions = {}
): SceneAction {
    const logic = notebookSelectButtonLogic({ ...notebookSelectButtonProps })
    const { loadNotebooksContainingResource, loadAllNotebooks } = useActions(logic)
    const { notebooksContainingResource, notebooksNotContainingResource } = useValues(logic)
    const { createNotebook } = useActions(notebooksModel)
    const { resource } = notebookSelectButtonProps || {}
    const notebookResource = resource && typeof resource !== 'boolean' ? resource : null

    const openAndAdd = (notebookShortId: string, exists: boolean): void => {
        void openNotebook(notebookShortId, NotebookTarget.Popover, (theNotebookLogic) => {
            if (!exists && notebookSelectButtonProps?.resource) {
                theNotebookLogic.actions.insertAfterLastNode([notebookSelectButtonProps.resource])
            }
        })
    }

    const notebookRow = (notebook: NotebookListItemType, exists: boolean): ActionMenuItem => ({
        id: `${exists ? 'in' : 'out'}-${notebook.short_id}`,
        // pinned: data-attr values are wire strings, shared by every row in the list
        dataAttr: exists ? `${dataAttrKey}-menubar-continue-notebook` : `${dataAttrKey}-menubar-add-notebook`,
        section: exists ? 'containing' : 'others',
        label: notebook.title || `Untitled (${notebook.short_id})`,
        icon: <IconNotebook />,
        opensFloatingUi: true,
        onSelect: () => openAndAdd(notebook.short_id, exists),
    })

    return {
        group,
        section,
        type: 'submenu',
        id: `${dataAttrKey}-menubar-add-to-notebook`,
        label: 'Add to notebook',
        display: 'submenu',
        searchable: false,
        onOpenChange: (open) => {
            if (!open) {
                return
            }
            if (resource) {
                loadNotebooksContainingResource()
            }
            loadAllNotebooks()
        },
        items: [
            {
                id: `${dataAttrKey}-menubar-new-notebook`,
                section: 'new',
                label: 'New notebook',
                icon: <IconPlusSmall />,
                opensFloatingUi: true,
                onSelect: () => {
                    const title = newNotebookTitle ?? `Notes ${dayjs().format('DD/MM')}`
                    createNotebook(
                        NotebookTarget.Popover,
                        title,
                        notebookResource ? [notebookResource] : undefined,
                        () => loadNotebooksContainingResource()
                    )
                },
            },
            {
                id: `${dataAttrKey}-menubar-scratchpad`,
                section: 'new',
                label: 'My scratchpad',
                icon: <IconNotebook />,
                opensFloatingUi: true,
                onSelect: () => openAndAdd('scratchpad', false),
            },
            ...notebooksContainingResource.map((notebook) => notebookRow(notebook, true)),
            ...notebooksNotContainingResource.map((notebook) => notebookRow(notebook, false)),
        ],
    }
}
