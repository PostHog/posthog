import { IconNotebook, IconPlus } from '@posthog/icons'
import { BuiltLogic, useActions, useValues } from 'kea'
import { dayjs } from 'lib/dayjs'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { useEffect } from 'react'
import { useNotebookNode } from 'scenes/notebooks/Nodes/NotebookNodeContext'
import { notebookNodeLogicType } from 'scenes/notebooks/Nodes/notebookNodeLogicType'
import { notebookLogicType } from 'scenes/notebooks/Notebook/notebookLogicType'
import {
    notebookSelectButtonLogic,
    NotebookSelectButtonLogicProps,
} from 'scenes/notebooks/NotebookSelectButton/notebookSelectButtonLogic'
import { notebooksModel, openNotebook } from '~/models/notebooksModel'
import { AccessControlLevel, AccessControlResourceType } from '~/types'
import { AccessControlAction } from '../../AccessControlAction'
import { SceneDataAttrKeyProps } from '../utils'
import { NotebookListItemType, NotebookTarget } from 'scenes/notebooks/types'

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
                <AccessControlAction
                    resourceType={AccessControlResourceType.Notebook}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    {({ disabledReason }) => (
                        <DropdownMenuItem
                            asChild
                            disabled={!!disabledReason}
                            {...(disabledReason && { tooltip: disabledReason })}
                            data-attr={`${dataAttrKey}-new-notebook-dropdown-menu-item`}
                        >
                            <ButtonPrimitive
                                menuItem
                                onClick={openNewNotebook}
                                data-attr={`${dataAttrKey}-new-notebook-button`}
                            >
                                <IconPlus />
                                New notebook
                            </ButtonPrimitive>
                        </DropdownMenuItem>
                    )}
                </AccessControlAction>
                <DropdownMenuItem asChild>
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
                </DropdownMenuItem>
            </DropdownMenuGroup>

            <DropdownMenuGroup>
                <DropdownMenuSeparator />
                {notebooksLoading && !notebooksNotContainingResource.length && !notebooksContainingResource.length ? (
                    <div className="px-2 py-1 flex flex-row items-center gap-x-1">
                        {notebooksLoading ? (
                            'Loading...'
                        ) : searchQuery.length ? (
                            <>No matching notebooks</>
                        ) : (
                            <>You have no notebooks</>
                        )}
                    </div>
                ) : (
                    <>
                        {resource ? (
                            <>
                                <DropdownMenuLabel>Continue in</DropdownMenuLabel>
                                {notebooksContainingResource.length > 0 ? (
                                    notebooksContainingResource.map((notebook: NotebookListItemType) => (
                                        <DropdownMenuItem
                                            key={notebook.short_id}
                                            onClick={() => {
                                                openAndAddToNotebook(notebook.short_id, true)
                                            }}
                                            data-attr={`${dataAttrKey}-continue-in-notebook-dropdown-menu-item`}
                                        >
                                            <ButtonPrimitive menuItem tooltip={notebook.title} tooltipPlacement="left">
                                                <IconNotebook />
                                                <span className="truncate">{notebook.title}</span>
                                            </ButtonPrimitive>
                                        </DropdownMenuItem>
                                    ))
                                ) : (
                                    <DropdownMenuItem>
                                        <ButtonPrimitive menuItem inert>
                                            <IconNotebook />
                                            No notebooks found
                                        </ButtonPrimitive>
                                    </DropdownMenuItem>
                                )}
                                <DropdownMenuSeparator />
                            </>
                        ) : null}
                        {resource ? <DropdownMenuLabel>Add to</DropdownMenuLabel> : null}
                        {notebooksNotContainingResource.length > 0 ? (
                            notebooksNotContainingResource.map((notebook: NotebookListItemType) => (
                                <DropdownMenuItem
                                    key={notebook.short_id}
                                    onClick={() => {
                                        openAndAddToNotebook(notebook.short_id, false)
                                    }}
                                    data-attr={`${dataAttrKey}-add-to-notebook-dropdown-menu-item`}
                                >
                                    <ButtonPrimitive menuItem tooltip={notebook.title} tooltipPlacement="left">
                                        <IconNotebook />
                                        <span className="truncate">{notebook.title}</span>
                                    </ButtonPrimitive>
                                </DropdownMenuItem>
                            ))
                        ) : (
                            <DropdownMenuItem>
                                <ButtonPrimitive menuItem inert>
                                    <IconNotebook />
                                    No notebooks found
                                </ButtonPrimitive>
                            </DropdownMenuItem>
                        )}
                    </>
                )}
            </DropdownMenuGroup>
        </>
    )
}
