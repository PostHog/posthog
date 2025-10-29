import { BuiltLogic, useActions, useValues } from 'kea'
import { ReactChild, ReactElement, useEffect } from 'react'

import { IconNotebook, IconPlus } from '@posthog/icons'
import { LemonDivider, LemonDropdown, LemonTag, ProfilePicture } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { MemberSelect } from 'lib/components/MemberSelect'
import { dayjs } from 'lib/dayjs'
import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { PopoverProps } from 'lib/lemon-ui/Popover'
import { IconWithCount } from 'lib/lemon-ui/icons'
import { useNotebookNode } from 'scenes/notebooks/Nodes/NotebookNodeContext'
import {
    NotebookSelectButtonLogicProps,
    notebookSelectButtonLogic,
} from 'scenes/notebooks/NotebookSelectButton/notebookSelectButtonLogic'

import { notebooksModel, openNotebook } from '~/models/notebooksModel'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { notebookNodeLogicType } from '../Nodes/notebookNodeLogicType'
import { notebookLogicType } from '../Notebook/notebookLogicType'
import { NotebookListItemType, NotebookTarget } from '../types'

export type NotebookSelectProps = NotebookSelectButtonLogicProps & {
    newNotebookTitle?: string
    onNotebookOpened?: (
        notebookLogic: BuiltLogic<notebookLogicType>,
        nodeLogic?: BuiltLogic<notebookNodeLogicType>
    ) => void
}

export type NotebookSelectPopoverProps = NotebookSelectProps &
    Partial<Omit<PopoverProps, 'children'>> & {
        children: ReactElement
    }

export type NotebookSelectButtonProps = NotebookSelectProps &
    Omit<LemonButtonProps, 'onClick' | 'children' | 'sideAction'> & {
        onClick?: () => void
        children?: ReactChild
    }

// Cleaning up Session Summaries notebooks to reduce repeated noise in the picker.
// If we match:
//  - show a small tag "Session summaries report" in the meta line
//  - strip that leading segment from the visible title
export const SESSION_SUMMARY_PREFIX = 'Session summaries report'
export const SESSION_PREFIX_REGEX = /^Session summaries report\s*[-–—:]*\s*/i
export const LEADING_SEPARATORS_REGEX = /^[\s]*[-–—:•·]+\s*/
export const TRAILING_DATE_REGEX = /\s*\(\d{4}-\d{2}-\d{2}\)\s*$/

export function isSessionSummaryTitle(title?: string): boolean {
    if (!title) {
        return false
    }
    return SESSION_PREFIX_REGEX.test(title.trim())
}
export function stripSessionSummaryPrefix(title?: string): string | null {
    if (title == null) {
        return null
    }
    if (!isSessionSummaryTitle(title)) {
        return title
    }
    // Remove the prefix and any immediately following separators
    let cleaned = title.replace(SESSION_PREFIX_REGEX, '')
    // Extra safety: if there are still leading separators, drop them
    cleaned = cleaned.replace(LEADING_SEPARATORS_REGEX, '')
    // Drop trailing date in parentheses e.g. (2025-10-28)
    cleaned = cleaned.replace(TRAILING_DATE_REGEX, '')
    return cleaned.trim()
}

function NotebooksChoiceList(props: {
    notebooks: NotebookListItemType[]
    emptyState: string
    onClick: (notebookShortId: NotebookListItemType['short_id']) => void
}): JSX.Element {
    return (
        <div>
            {props.notebooks.length === 0 ? (
                <div className="px-2 py-1">{props.emptyState}</div>
            ) : (
                props.notebooks.map((notebook, i) => {
                    const isSession = isSessionSummaryTitle(notebook.title || undefined)
                    const renderedTitle = isSession
                        ? stripSessionSummaryPrefix(notebook.title || undefined) || notebook.title
                        : notebook.title
                    return (
                        <LemonButton
                            key={i}
                            sideIcon={
                                notebook.created_by ? (
                                    <ProfilePicture
                                        user={notebook.created_by}
                                        size="md"
                                        title={`Created by ${notebook.created_by?.first_name} <${notebook.created_by?.email}>`}
                                    />
                                ) : null
                            }
                            fullWidth
                            onClick={() => props.onClick(notebook.short_id)}
                        >
                            <div className="flex flex-col text-left w-full">
                                <span className="truncate">{renderedTitle || `Untitled (${notebook.short_id})`}</span>
                                <span className="text-muted-alt text-xs">
                                    {notebook.created_by?.first_name || notebook.created_by?.email || 'Unknown'}
                                    {` · ${dayjs(notebook.last_modified_at ?? notebook.created_at).fromNow()}`}
                                    {isSession ? (
                                        <LemonTag size="small" type="muted" className="ml-2 inline-block align-middle">
                                            {SESSION_SUMMARY_PREFIX}
                                        </LemonTag>
                                    ) : null}
                                </span>
                            </div>
                        </LemonButton>
                    )
                })
            )}
        </div>
    )
}

export function NotebookSelectList(props: NotebookSelectProps): JSX.Element {
    const logic = notebookSelectButtonLogic({ ...props })

    const { resource, newNotebookTitle } = props
    const notebookResource = resource && typeof resource !== 'boolean' ? resource : null
    const { notebooksLoading, notebooksContainingResource, notebooksNotContainingResource, searchQuery, createdBy } =
        useValues(logic as any)
    const { setShowPopover, setSearchQuery, setCreatedBy, loadNotebooksContainingResource, loadAllNotebooks } =
        useActions(logic as any)
    const { createNotebook } = useActions(notebooksModel)

    const openAndAddToNotebook = (notebookShortId: string, exists: boolean): void => {
        const position = props.resource ? 'end' : 'start'
        void openNotebook(notebookShortId, NotebookTarget.Popover, position, (theNotebookLogic) => {
            if (!exists && props.resource) {
                theNotebookLogic.actions.insertAfterLastNode([props.resource])
            }
            props.onNotebookOpened?.(theNotebookLogic)
        })
    }

    const openNewNotebook = (): void => {
        const title = newNotebookTitle ?? `Notes ${dayjs().format('DD/MM')}`

        createNotebook(
            NotebookTarget.Popover,
            title,
            notebookResource ? [notebookResource] : undefined,
            (theNotebookLogic) => {
                props.onNotebookOpened?.(theNotebookLogic)
                loadNotebooksContainingResource()
            }
        )

        setShowPopover(false)
    }

    useEffect(() => {
        if (props.resource) {
            loadNotebooksContainingResource()
        }
        loadAllNotebooks()
        // oxlint-disable-next-line exhaustive-deps
    }, [loadAllNotebooks])

    return (
        <div className="flex flex-col flex-1 h-full overflow-hidden">
            <div className="deprecated-space-y-2 flex-0">
                <div className="flex gap-2 items-center">
                    <LemonInput
                        type="search"
                        placeholder="Search notebooks..."
                        value={searchQuery}
                        onChange={(s) => setSearchQuery(s)}
                        fullWidth
                    />
                    <div className="min-w-48">
                        <MemberSelect
                            value={createdBy}
                            onChange={(user) => setCreatedBy(user?.uuid ?? null)}
                            size="small"
                        />
                    </div>
                </div>
                <AccessControlAction
                    resourceType={AccessControlResourceType.Notebook}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <LemonButton
                        data-attr="notebooks-select-button-create"
                        fullWidth
                        icon={<IconPlus />}
                        onClick={openNewNotebook}
                    >
                        New notebook
                    </LemonButton>
                </AccessControlAction>

                <LemonButton
                    fullWidth
                    onClick={() => {
                        setShowPopover(false)
                        openAndAddToNotebook('scratchpad', false)
                    }}
                >
                    My scratchpad
                </LemonButton>
            </div>
            <LemonDivider />
            <div className="overflow-y-auto flex-1">
                {notebooksLoading && !notebooksNotContainingResource.length && !notebooksContainingResource.length ? (
                    <div className="px-2 py-1 flex flex-row items-center deprecated-space-x-1">
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
                                <h5>Continue in</h5>
                                <NotebooksChoiceList
                                    notebooks={notebooksContainingResource}
                                    emptyState={
                                        searchQuery.length ? 'No matching notebooks' : 'Not already in any notebooks'
                                    }
                                    onClick={(notebookShortId) => {
                                        setShowPopover(false)
                                        openAndAddToNotebook(notebookShortId, true)
                                    }}
                                />
                                <LemonDivider />
                            </>
                        ) : null}
                        {resource ? <h5>Add to</h5> : null}
                        <NotebooksChoiceList
                            notebooks={notebooksNotContainingResource}
                            emptyState={searchQuery.length ? 'No matching notebooks' : "You don't have any notebooks"}
                            onClick={(notebookShortId) => {
                                setShowPopover(false)
                                openAndAddToNotebook(notebookShortId, false)
                            }}
                        />
                    </>
                )}
            </div>
        </div>
    )
}

export function NotebookSelectPopover({
    // so we can pass props to the button below, without passing visible to it
    visible,
    children,
    ...props
}: NotebookSelectPopoverProps): JSX.Element {
    const logic = notebookSelectButtonLogic({ ...props, visible })
    const { showPopover } = useValues(logic)
    const { setShowPopover } = useActions(logic)

    const onNotebookOpened: NotebookSelectProps['onNotebookOpened'] = (...args) => {
        setShowPopover(false)
        props.onNotebookOpened?.(...args)
    }

    return (
        <LemonDropdown
            overlay={
                <div className="max-w-160">
                    <NotebookSelectList {...props} onNotebookOpened={onNotebookOpened} />
                </div>
            }
            matchWidth={false}
            actionable
            visible={!!showPopover}
            onVisibilityChange={(visible) => setShowPopover(visible)}
            closeOnClickInside={false}
        >
            {children}
        </LemonDropdown>
    )
}

export function NotebookSelectButton({ children, onNotebookOpened, ...props }: NotebookSelectButtonProps): JSX.Element {
    // if nodeLogic is available then the button is on a resource that _is already and currently in a notebook_
    const nodeLogic = useNotebookNode()
    const logic = notebookSelectButtonLogic({ ...props, onNotebookOpened })
    const { showPopover, notebooksContainingResource } = useValues(logic)
    const { loadNotebooksContainingResource } = useActions(logic)

    useEffect(() => {
        if (!nodeLogic) {
            loadNotebooksContainingResource()
        }
        // oxlint-disable-next-line exhaustive-deps
    }, [nodeLogic])

    const button = (
        <LemonButton
            icon={
                <IconWithCount count={notebooksContainingResource.length ?? 0} showZero={false}>
                    <IconNotebook />
                </IconWithCount>
            }
            data-attr={nodeLogic ? 'notebooks-add-button-in-a-notebook' : 'notebooks-add-button'}
            sideIcon={null}
            {...props}
            active={showPopover}
            onClick={() => {
                props.onClick?.()
                if (nodeLogic) {
                    // If we are in a Notebook then we just call the callback directly
                    onNotebookOpened?.(nodeLogic.props.notebookLogic, nodeLogic)
                }
            }}
            tooltip="Add to notebook"
        >
            {children ?? 'Notebooks'}
        </LemonButton>
    )

    return nodeLogic ? button : <NotebookSelectPopover {...props}>{button}</NotebookSelectPopover>
}
