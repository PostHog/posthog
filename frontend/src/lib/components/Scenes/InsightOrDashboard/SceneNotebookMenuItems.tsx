import { BuiltLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconNotebook, IconPlusSmall } from '@posthog/icons'

import { dayjs } from 'lib/dayjs'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { Combobox } from 'lib/ui/Combobox/Combobox'
import { DropdownMenuGroup, DropdownMenuSeparator } from 'lib/ui/DropdownMenu/DropdownMenu'
import { Label } from 'lib/ui/Label/Label'
import { useNotebookNode } from 'scenes/notebooks/Nodes/NotebookNodeContext'
import { notebookNodeLogicType } from 'scenes/notebooks/Nodes/notebookNodeLogicType'
import { notebookLogicType } from 'scenes/notebooks/Notebook/notebookLogicType'
import {
    NotebookSelectButtonLogicProps,
    notebookSelectButtonLogic,
} from 'scenes/notebooks/NotebookSelectButton/notebookSelectButtonLogic'
import { NotebookListItemType, NotebookTarget } from 'scenes/notebooks/types'

import { notebooksModel, openNotebook } from '~/models/notebooksModel'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { AccessControlAction } from '../../AccessControlAction'
import { SceneDataAttrKeyProps } from '../utils'

type SceneNotebookDropdownMenuProps = SceneDataAttrKeyProps & {
    notebookSelectButtonProps?: NotebookSelectButtonLogicProps
    newNotebookTitle?: string
    onNotebookOpened?: (
        notebookLogic: BuiltLogic<notebookLogicType>,
        nodeLogic?: BuiltLogic<notebookNodeLogicType>
    ) => void
}

export function SceneNotebookMenuItems({
    notebookSelectButtonProps,
    newNotebookTitle,
    onNotebookOpened,
    dataAttrKey,
}: SceneNotebookDropdownMenuProps): JSX.Element {
    const logic = notebookSelectButtonLogic({ ...notebookSelectButtonProps })
    const { loadNotebooksContainingResource, loadAllNotebooks } = useActions(logic)
    const nodeLogic = useNotebookNode()
    const { notebooksLoading, notebooksContainingResource, notebooksNotContainingResource, searchQuery } =
        useValues(logic)
    const { resource } = notebookSelectButtonProps || {}
    const { createNotebook } = useActions(notebooksModel)
    const notebookResource = resource && typeof resource !== 'boolean' ? resource : null

    const openAndAddToNotebook = (notebookShortId: string, exists: boolean): void => {
        const position = notebookSelectButtonProps?.resource ? 'end' : 'start'
        void openNotebook(notebookShortId, NotebookTarget.Popover, position, (theNotebookLogic) => {
            if (!exists && notebookSelectButtonProps?.resource) {
                theNotebookLogic.actions.insertAfterLastNode([notebookSelectButtonProps.resource])
            }
        })
    }

    const openNewNotebook = (): void => {
        const title = newNotebookTitle ?? `Notes ${dayjs().format('DD/MM')}`

        createNotebook(
            NotebookTarget.Popover,
            title,
            notebookResource ? [notebookResource] : undefined,
            (theNotebookLogic) => {
                onNotebookOpened?.(theNotebookLogic)
                loadNotebooksContainingResource()
            }
        )
    }

    useEffect(() => {
        if (!nodeLogic) {
            if (resource) {
                loadNotebooksContainingResource()
            }
            loadAllNotebooks()
        }
        // oxlint-disable-next-line exhaustive-deps
    }, [nodeLogic, resource])

    return (
        <>
            <DropdownMenuGroup>
                <Combobox insideMenu>
                    <Combobox.Search placeholder="Search notebooks..." autoFocus />

                    <Combobox.Content className="max-w-none min-w-none">
                        <Combobox.Empty>No notebooks found</Combobox.Empty>

                        <AccessControlAction
                            resourceType={AccessControlResourceType.Notebook}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            {({ disabledReason }) => (
                                <Combobox.Group>
                                    <Combobox.Item asChild>
                                        <ButtonPrimitive
                                            menuItem
                                            onClick={openNewNotebook}
                                            data-attr={`${dataAttrKey}-new-notebook-button`}
                                            disabled={!!disabledReason}
                                            {...(disabledReason && { tooltip: disabledReason })}
                                        >
                                            <IconPlusSmall />
                                            New notebook
                                        </ButtonPrimitive>
                                    </Combobox.Item>
                                </Combobox.Group>
                            )}
                        </AccessControlAction>

                        <Combobox.Group value={['My scratchpad']}>
                            <Combobox.Item asChild>
                                <ButtonPrimitive
                                    menuItem
                                    onClick={() => {
                                        openAndAddToNotebook('scratchpad', false)
                                    }}
                                    data-attr={`${dataAttrKey}-my-scratchpad-dropdown-menu-item`}
                                >
                                    <IconNotebook />
                                    My scratchpad
                                </ButtonPrimitive>
                            </Combobox.Item>
                        </Combobox.Group>

                        {notebooksLoading &&
                        !notebooksNotContainingResource.length &&
                        !notebooksContainingResource.length ? (
                            <Combobox.Group>
                                <Combobox.Item asChild>
                                    <div className="px-2 py-1 flex flex-row items-center gap-x-1">
                                        {notebooksLoading ? (
                                            'Loading...'
                                        ) : searchQuery.length ? (
                                            <>No matching notebooks</>
                                        ) : (
                                            <>You have no notebooks</>
                                        )}
                                    </div>
                                </Combobox.Item>
                            </Combobox.Group>
                        ) : (
                            <>
                                {resource ? (
                                    <>
                                        <Label intent="menu" className="px-2 mt-2">
                                            Continue in
                                        </Label>
                                        <DropdownMenuSeparator />
                                        {notebooksContainingResource.length > 0 ? (
                                            notebooksContainingResource.map(
                                                (notebook: NotebookListItemType) =>
                                                    notebook && (
                                                        <Combobox.Group value={[notebook.title ?? '']}>
                                                            <Combobox.Item key={notebook.short_id} asChild>
                                                                <ButtonPrimitive
                                                                    menuItem
                                                                    onClick={() => {
                                                                        openAndAddToNotebook(notebook.short_id, true)
                                                                    }}
                                                                    data-attr={`${dataAttrKey}-continue-in-notebook-dropdown-menu-item`}
                                                                >
                                                                    <IconNotebook />
                                                                    {notebook.title ||
                                                                        `Untitled (${notebook.short_id})`}
                                                                </ButtonPrimitive>
                                                            </Combobox.Item>
                                                        </Combobox.Group>
                                                    )
                                            )
                                        ) : (
                                            <ButtonPrimitive menuItem inert className="text-tertiary">
                                                No notebooks found
                                            </ButtonPrimitive>
                                        )}
                                    </>
                                ) : null}
                                {resource ? (
                                    <>
                                        <Label intent="menu" className="px-2 mt-2">
                                            Add to
                                        </Label>
                                        <DropdownMenuSeparator />
                                        {notebooksNotContainingResource.length > 0 ? (
                                            notebooksNotContainingResource.map(
                                                (notebook: NotebookListItemType) =>
                                                    notebook && (
                                                        <Combobox.Group value={[notebook.title ?? '']}>
                                                            <Combobox.Item key={notebook.short_id} asChild>
                                                                <ButtonPrimitive
                                                                    menuItem
                                                                    onClick={() => {
                                                                        openAndAddToNotebook(notebook.short_id, false)
                                                                    }}
                                                                    data-attr={`${dataAttrKey}-add-to-notebook-dropdown-menu-item`}
                                                                >
                                                                    <IconNotebook />
                                                                    {notebook.title ||
                                                                        `Untitled (${notebook.short_id})`}
                                                                </ButtonPrimitive>
                                                            </Combobox.Item>
                                                        </Combobox.Group>
                                                    )
                                            )
                                        ) : (
                                            <ButtonPrimitive menuItem inert className="text-tertiary">
                                                No notebooks found
                                            </ButtonPrimitive>
                                        )}
                                    </>
                                ) : null}
                            </>
                        )}
                    </Combobox.Content>
                </Combobox>
            </DropdownMenuGroup>
        </>
    )
}
