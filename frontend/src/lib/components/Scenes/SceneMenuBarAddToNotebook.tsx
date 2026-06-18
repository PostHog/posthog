import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconNotebook, IconPlusSmall } from '@posthog/icons'

import { dayjs } from 'lib/dayjs'
import {
    NotebookSelectButtonLogicProps,
    notebookSelectButtonLogic,
} from 'scenes/notebooks/NotebookSelectButton/notebookSelectButtonLogic'
import { NotebookListItemType, NotebookTarget } from 'scenes/notebooks/types'

import { SceneMenuBarItem, SceneMenuBarSeparator, SceneMenuBarSubMenu } from '~/layout/scenes/components/SceneMenuBar'
import { notebooksModel, openNotebook } from '~/models/notebooksModel'

type SceneMenuBarAddToNotebookProps = {
    dataAttrKey: string
    notebookSelectButtonProps?: NotebookSelectButtonLogicProps
    /** Title used when "New notebook" is clicked */
    newNotebookTitle?: string
}

/**
 * Add-to-notebook sub-menu intended to live inside a `<SceneMenuBarMenu label="Create">`.
 * Renders a sub-menu trigger that, on open, shows:
 *   - New notebook
 *   - Scratchpad
 *   - Notebooks already containing this resource (if any)
 *   - Other notebooks (capped by `NOTEBOOK_DROPDOWN_LIMIT`)
 */
export function SceneMenuBarAddToNotebook({
    dataAttrKey,
    notebookSelectButtonProps,
    newNotebookTitle,
}: SceneMenuBarAddToNotebookProps): JSX.Element {
    const logic = notebookSelectButtonLogic({ ...notebookSelectButtonProps })
    const { loadNotebooksContainingResource, loadAllNotebooks } = useActions(logic)
    const { notebooksContainingResource, notebooksNotContainingResource } = useValues(logic)
    const { createNotebook } = useActions(notebooksModel)
    const { resource } = notebookSelectButtonProps || {}
    const notebookResource = resource && typeof resource !== 'boolean' ? resource : null

    useEffect(() => {
        if (resource) {
            loadNotebooksContainingResource()
        }
        loadAllNotebooks()
        // oxlint-disable-next-line exhaustive-deps
    }, [resource])

    const openAndAdd = (notebookShortId: string, exists: boolean): void => {
        const position = notebookSelectButtonProps?.resource ? 'end' : 'start'
        void openNotebook(notebookShortId, NotebookTarget.Popover, position, (theNotebookLogic) => {
            if (!exists && notebookSelectButtonProps?.resource) {
                theNotebookLogic.actions.insertAfterLastNode([notebookSelectButtonProps.resource])
            }
        })
    }

    const openNew = (): void => {
        const title = newNotebookTitle ?? `Notes ${dayjs().format('DD/MM')}`
        createNotebook(NotebookTarget.Popover, title, notebookResource ? [notebookResource] : undefined, () => {
            loadNotebooksContainingResource()
        })
    }

    return (
        <SceneMenuBarSubMenu label="Add to notebook">
            <SceneMenuBarItem opensFloatingUi onClick={openNew} data-attr={`${dataAttrKey}-menubar-new-notebook`}>
                <IconPlusSmall />
                New notebook
            </SceneMenuBarItem>
            <SceneMenuBarItem
                opensFloatingUi
                onClick={() => openAndAdd('scratchpad', false)}
                data-attr={`${dataAttrKey}-menubar-scratchpad`}
            >
                <IconNotebook />
                My scratchpad
            </SceneMenuBarItem>
            {notebooksContainingResource.length > 0 && <SceneMenuBarSeparator />}
            {notebooksContainingResource.map((notebook: NotebookListItemType) => (
                <SceneMenuBarItem
                    key={`in-${notebook.short_id}`}
                    opensFloatingUi
                    onClick={() => openAndAdd(notebook.short_id, true)}
                    data-attr={`${dataAttrKey}-menubar-continue-notebook`}
                >
                    <IconNotebook />
                    {notebook.title || `Untitled (${notebook.short_id})`}
                </SceneMenuBarItem>
            ))}
            {notebooksNotContainingResource.length > 0 && <SceneMenuBarSeparator />}
            {notebooksNotContainingResource.map((notebook: NotebookListItemType) => (
                <SceneMenuBarItem
                    key={`out-${notebook.short_id}`}
                    opensFloatingUi
                    onClick={() => openAndAdd(notebook.short_id, false)}
                    data-attr={`${dataAttrKey}-menubar-add-notebook`}
                >
                    <IconNotebook />
                    {notebook.title || `Untitled (${notebook.short_id})`}
                </SceneMenuBarItem>
            ))}
        </SceneMenuBarSubMenu>
    )
}
