import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'

import { IconPlus, IconWithCount } from 'lib/lemon-ui/icons'
import {
    NotebookSelectButtonLogicProps,
    notebookSelectButtonLogic,
} from 'scenes/notebooks/NotebookSelectButton/notebookSelectButtonLogic'
import { BuiltLogic, useActions, useValues } from 'kea'
import { dayjs } from 'lib/dayjs'
import { NotebookListItemType, NotebookTarget } from '~/types'
import { notebooksModel, openNotebook } from '~/models/notebooksModel'
import { useNotebookNode } from 'scenes/notebooks/Nodes/notebookNodeLogic'
import { Popover, PopoverProps } from 'lib/lemon-ui/Popover'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { notebookLogicType } from '../Notebook/notebookLogicType'
import { notebookNodeLogicType } from '../Nodes/notebookNodeLogicType'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import { ReactChild, useEffect } from 'react'
import { LemonDivider, ProfilePicture } from '@posthog/lemon-ui'
import { IconNotebook } from '../IconNotebook'

export type NotebookSelectProps = NotebookSelectButtonLogicProps & {
    newNotebookTitle?: string
    onNotebookOpened?: (
        notebookLogic: BuiltLogic<notebookLogicType>,
        nodeLogic?: BuiltLogic<notebookNodeLogicType>
    ) => void
}

export type NotebookSelectPopoverProps = NotebookSelectProps &
    Partial<PopoverProps> & {
        children?: ReactChild
    }

export type NotebookSelectButtonProps = NotebookSelectProps &
    Omit<LemonButtonProps, 'onClick' | 'children'> & {
        onClick?: () => void
        children?: ReactChild
    }

function NotebooksChoiceList(props: {
    notebooks: NotebookListItemType[]
    emptyState: string
    onClick: (notebookShortId: NotebookListItemType['short_id']) => void
}): JSX.Element {
    return (
        <div>
            {props.notebooks.length === 0 ? (
                <div className={'px-2 py-1'}>{props.emptyState}</div>
            ) : (
                props.notebooks.map((notebook, i) => {
                    return (
                        <LemonButton
                            key={i}
                            sideIcon={
                                notebook.created_by ? (
                                    <ProfilePicture
                                        name={notebook.created_by?.first_name}
                                        email={notebook.created_by?.email}
                                        size="md"
                                        title={`Created by ${notebook.created_by?.first_name} <${notebook.created_by?.email}>`}
                                    />
                                ) : null
                            }
                            fullWidth
                            onClick={() => props.onClick(notebook.short_id)}
                        >
                            <span className="truncate">{notebook.title || `Untitled (${notebook.short_id})`}</span>
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
    const { notebooksLoading, notebooksContainingResource, notebooksNotContainingResource, searchQuery } =
        useValues(logic)
    const { setShowPopover, setSearchQuery, loadNotebooksContainingResource, loadAllNotebooks } = useActions(logic)
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
    }, [])

    return (
        <div className="flex flex-col flex-1 h-full overflow-hidden">
            <div className="space-y-2 flex-0">
                <LemonInput
                    type="search"
                    placeholder="Search notebooks..."
                    value={searchQuery}
                    onChange={(s) => setSearchQuery(s)}
                    fullWidth
                />
                <LemonButton
                    data-attr="notebooks-select-button-create"
                    fullWidth
                    icon={<IconPlus />}
                    onClick={openNewNotebook}
                >
                    New notebook
                </LemonButton>
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
                    <div className={'px-2 py-1 flex flex-row items-center space-x-1'}>
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

    return (
        <Popover
            visible={!!showPopover}
            onClickOutside={() => setShowPopover(false)}
            actionable
            overlay={
                <div className="max-w-160">
                    <NotebookSelectList {...props} />
                </div>
            }
            {...props}
        >
            <span onClick={() => setShowPopover(true)}>{children}</span>
        </Popover>
    )
}

export function NotebookSelectButton({ children, ...props }: NotebookSelectButtonProps): JSX.Element {
    // if nodeLogic is available then the button is on a resource that _is already and currently in a notebook_
    const nodeLogic = useNotebookNode()
    const logic = notebookSelectButtonLogic({ ...props })
    const { showPopover, notebooksLoading, notebooksContainingResource } = useValues(logic)
    const { loadNotebooksContainingResource } = useActions(logic)

    useEffect(() => {
        if (!nodeLogic) {
            loadNotebooksContainingResource()
        }
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
            loading={notebooksLoading}
            onClick={() => {
                props.onClick?.()
                if (nodeLogic) {
                    // If we are in a Notebook then we just call the callback directly
                    props.onNotebookOpened?.(nodeLogic.props.notebookLogic, nodeLogic)
                }
            }}
        >
            {children ?? 'Add to notebook'}
        </LemonButton>
    )

    return (
        <FlaggedFeature flag={FEATURE_FLAGS.NOTEBOOKS} match>
            {nodeLogic ? button : <NotebookSelectPopover {...props}>{button}</NotebookSelectPopover>}
        </FlaggedFeature>
    )
}
