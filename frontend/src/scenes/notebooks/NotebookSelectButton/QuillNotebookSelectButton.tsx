import { useActions, useValues } from 'kea'
import { type KeyboardEvent, useEffect } from 'react'

import { IconNotebook, IconPlus, IconSearch } from '@posthog/icons'
import {
    Badge,
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
} from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { useNotebookNode } from 'scenes/notebooks/Nodes/NotebookNodeContext'

import { notebooksModel } from '~/models/notebooksModel'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { NotebookListItemType } from '../types'
import { createNotebookForResource, openNotebookForResource } from './notebookSelectActions'
import type { NotebookSelectProps } from './NotebookSelectButton'
import { NOTEBOOK_DROPDOWN_LIMIT, notebookSelectButtonLogic } from './notebookSelectButtonLogic'
import { QuillNotebookFilterMenu } from './QuillNotebookFilterMenu'
import { QuillNotebookMenuItem } from './QuillNotebookMenuItem'
import { QuillNotebookMenuNote } from './QuillNotebookMenuNote'

// A menu treats typed letters as jumps to a matching item, which would steal keys from the search field.
// Arrow down and escape still reach the menu, so the list stays reachable and the menu closes as usual.
function keepTypingInField(event: KeyboardEvent<HTMLInputElement>): void {
    if (event.key !== 'ArrowDown' && event.key !== 'Escape') {
        event.stopPropagation()
    }
}

/**
 * Not rendered anywhere. The rail redesign (`today-rail-nav`) deprecates adding to notebooks from outside a notebook:
 * under the flag, `NotebookSelectButton` and `SceneAddToNotebookDropdownMenu` render nothing, and the replay menu and
 * the insight, feature flag and cohort menu bars leave their "Add to notebook" entry out. To bring the picker back,
 * remove those gates and render this component where the flag is on, with the same `resource` the Lemon button gets.
 */
export function QuillNotebookSelectButton({
    resource,
    newNotebookTitle,
    onNotebookOpened,
}: NotebookSelectProps): JSX.Element {
    // Inside a notebook, the resource is already in one, so the button hands it straight to the callback.
    const nodeLogic = useNotebookNode()
    const logic = notebookSelectButtonLogic({ resource })
    const {
        showPopover,
        notebooksLoading,
        notebooksContainingResource,
        notebooksNotContainingResource,
        searchQuery,
        createdBy,
    } = useValues(logic)
    const { setShowPopover, setSearchQuery, setCreatedBy, loadNotebooksContainingResource, loadAllNotebooks } =
        useActions(logic)
    const { createNotebook } = useActions(notebooksModel)

    useEffect(() => {
        if (!nodeLogic) {
            loadNotebooksContainingResource()
        }
        // oxlint-disable-next-line exhaustive-deps
    }, [nodeLogic])

    const containingCount = notebooksContainingResource.length
    const triggerContent = (
        <>
            <IconNotebook />
            Notebooks
            {containingCount > 0 && <Badge>{containingCount}</Badge>}
        </>
    )

    if (nodeLogic) {
        return (
            <Button
                variant="outline"
                tooltip="Add to notebook"
                onClick={() => onNotebookOpened?.(nodeLogic.props.notebookLogic, nodeLogic)}
                data-attr="notebooks-add-button-in-a-notebook"
            >
                {triggerContent}
            </Button>
        )
    }

    const openAndAddToNotebook = (notebook: NotebookListItemType, alreadyContainsResource: boolean): void =>
        openNotebookForResource({
            notebookShortId: notebook.short_id,
            alreadyContainsResource,
            resource,
            onNotebookOpened,
        })
    const emptyList = searchQuery.length ? 'No matching notebooks' : undefined
    const atLimit =
        notebooksContainingResource.length >= NOTEBOOK_DROPDOWN_LIMIT ||
        notebooksNotContainingResource.length >= NOTEBOOK_DROPDOWN_LIMIT

    return (
        <DropdownMenu
            // The filter menu opens its own popup outside this menu, which a modal menu would block.
            modal={false}
            open={!!showPopover}
            onOpenChange={(open) => {
                setShowPopover(open)
                if (open) {
                    loadAllNotebooks()
                    if (resource) {
                        loadNotebooksContainingResource()
                    }
                }
            }}
        >
            <DropdownMenuTrigger
                render={<Button variant="outline" tooltip="Add to notebook" data-attr="notebooks-add-button" />}
            >
                {triggerContent}
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-80">
                <div className="flex items-center gap-1 p-1">
                    <InputGroup size="sm" className="flex-1">
                        <InputGroupAddon align="inline-start">
                            <IconSearch />
                        </InputGroupAddon>
                        <InputGroupInput
                            placeholder="Filter notebooks..."
                            aria-label="Filter notebooks"
                            value={searchQuery}
                            onChange={(event) => setSearchQuery(event.target.value)}
                            onKeyDown={keepTypingInField}
                            autoFocus
                        />
                    </InputGroup>
                    <QuillNotebookFilterMenu createdBy={createdBy} setCreatedBy={setCreatedBy} />
                </div>
                <DropdownMenuGroup>
                    <AccessControlAction
                        resourceType={AccessControlResourceType.Notebook}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <DropdownMenuItem
                            onClick={() =>
                                createNotebookForResource({
                                    resource,
                                    newNotebookTitle,
                                    createNotebook,
                                    onNotebookOpened: (theNotebookLogic) => {
                                        onNotebookOpened?.(theNotebookLogic)
                                        loadNotebooksContainingResource()
                                    },
                                })
                            }
                            data-attr="notebooks-select-button-create"
                        >
                            <IconPlus />
                            New notebook
                        </DropdownMenuItem>
                    </AccessControlAction>
                    <DropdownMenuItem
                        onClick={() =>
                            openNotebookForResource({
                                notebookShortId: 'scratchpad',
                                alreadyContainsResource: false,
                                resource,
                                onNotebookOpened,
                            })
                        }
                    >
                        <IconNotebook />
                        My scratchpad
                    </DropdownMenuItem>
                </DropdownMenuGroup>
                <DropdownMenuSeparator />
                {notebooksLoading && !notebooksContainingResource.length && !notebooksNotContainingResource.length ? (
                    <QuillNotebookMenuNote>Loading...</QuillNotebookMenuNote>
                ) : (
                    <>
                        {resource ? (
                            <>
                                <DropdownMenuGroup>
                                    <DropdownMenuLabel>Continue in</DropdownMenuLabel>
                                    {notebooksContainingResource.length ? (
                                        notebooksContainingResource.map((notebook) => (
                                            <QuillNotebookMenuItem
                                                key={notebook.short_id}
                                                notebook={notebook}
                                                onClick={() => openAndAddToNotebook(notebook, true)}
                                            />
                                        ))
                                    ) : (
                                        <QuillNotebookMenuNote>
                                            {emptyList ?? 'Not already in any notebooks'}
                                        </QuillNotebookMenuNote>
                                    )}
                                </DropdownMenuGroup>
                                <DropdownMenuSeparator />
                            </>
                        ) : null}
                        <DropdownMenuGroup>
                            {resource ? <DropdownMenuLabel>Add to</DropdownMenuLabel> : null}
                            {notebooksNotContainingResource.length ? (
                                notebooksNotContainingResource.map((notebook) => (
                                    <QuillNotebookMenuItem
                                        key={notebook.short_id}
                                        notebook={notebook}
                                        onClick={() => openAndAddToNotebook(notebook, false)}
                                    />
                                ))
                            ) : (
                                <QuillNotebookMenuNote>
                                    {emptyList ?? "You don't have any notebooks"}
                                </QuillNotebookMenuNote>
                            )}
                        </DropdownMenuGroup>
                        {atLimit && (
                            <QuillNotebookMenuNote>
                                Showing first {NOTEBOOK_DROPDOWN_LIMIT} results. Use search to narrow down.
                            </QuillNotebookMenuNote>
                        )}
                    </>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
