import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'

import { IconComment, IconPlus, IconWithCount } from 'lib/lemon-ui/icons'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { notebookCommentButtonLogic } from 'scenes/notebooks/NotebookCommentButton/notebookCommentButtonLogic'
import { useActions, useValues } from 'kea'
import { LemonMenuProps } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { dayjs } from 'lib/dayjs'
import { NotebookListItemType, NotebookNodeType, NotebookTarget } from '~/types'
import { buildTimestampCommentContent } from 'scenes/notebooks/Nodes/NotebookNodeReplayTimestamp'
import { notebooksListLogic, openNotebook } from 'scenes/notebooks/Notebook/notebooksListLogic'
import { useNotebookNode } from 'scenes/notebooks/Nodes/notebookNodeLogic'
import { Popover } from 'lib/lemon-ui/Popover'
import { useEffect, useState } from 'react'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { buildRecordingContent } from 'scenes/notebooks/Nodes/NotebookNodeRecording'

interface NotebookCommentButtonProps extends Pick<LemonButtonProps, 'size'>, Pick<LemonMenuProps, 'visible'> {
    sessionRecordingId: string
    getCurrentPlayerTime: () => number
}

function NotebooksChoiceList(props: {
    notebooksLoading: boolean
    notebooks: NotebookListItemType[]
    emptyState: string
    loadingState?: string
    onClick: (notebookShortId: NotebookListItemType['short_id']) => void
}): JSX.Element {
    return (
        <div>
            {props.notebooksLoading ? (
                <div className={'px-2 py-1 flex flex-row items-center space-x-1'}>
                    <Spinner />
                    <span>{props.loadingState}</span>
                </div>
            ) : props.notebooks.length === 0 ? (
                <div className={'px-2 py-1'}>{props.emptyState}</div>
            ) : (
                props.notebooks.map((notebook, i) => {
                    return (
                        <LemonButton key={i} fullWidth onClick={() => props.onClick(notebook.short_id)}>
                            {notebook.title || 'unknown title'}
                        </LemonButton>
                    )
                })
            )}
        </div>
    )
}

function RecordingCommentChoice({
    visible,
    sessionRecordingId,
    getCurrentPlayerTime,
    size,
}: NotebookCommentButtonProps): JSX.Element {
    const logic = notebookCommentButtonLogic({ sessionRecordingId, startVisible: !!visible })
    const { createNotebook, loadNotebooks } = useActions(notebooksListLogic)
    const { notebooks: allNotebooks, notebooksLoading: allNotebooksLoading } = useValues(notebooksListLogic)
    const { showPopover, notebooksLoading, notebooks: currentNotebooks } = useValues(logic)
    const { setShowPopover } = useActions(logic)

    const [searchQuery, setSearchQuery] = useState('')

    useEffect(() => {
        // really this should be connected in a logic,
        // but there was a horrible circular dependency confusing matters
        loadNotebooks()
    }, [])

    const commentInNewNotebook = (): void => {
        const title = `Session Replay Notes ${dayjs().format('DD/MM')}`
        const currentPlayerTime = getCurrentPlayerTime() * 1000
        createNotebook(
            title,
            NotebookTarget.Popover,
            [
                {
                    type: NotebookNodeType.Recording,
                    attrs: { id: sessionRecordingId },
                },
                buildTimestampCommentContent(currentPlayerTime, sessionRecordingId),
            ],
            () => {
                // refresh the comment button so that it includes the new notebook
                // after the new notebook is created
                notebookCommentButtonLogic.findMounted({ sessionRecordingId })?.actions.loadContainingNotebooks()
            }
        )
    }

    const commentInExistingNotebook = async (notebookShortId: string): Promise<void> => {
        const currentPlayerTime = getCurrentPlayerTime() * 1000
        await openNotebook(notebookShortId, NotebookTarget.Popover, null, (theNotebookLogic) => {
            theNotebookLogic.actions.insertReplayCommentByTimestamp(currentPlayerTime, sessionRecordingId)
        })
    }

    const addToAndCommentInExistingNotebook = async (notebookShortId: string): Promise<void> => {
        const currentPlayerTime = getCurrentPlayerTime() * 1000
        await openNotebook(notebookShortId, NotebookTarget.Popover, null, (theNotebookLogic) => {
            theNotebookLogic.actions.insertAfterLastNode([
                buildRecordingContent(sessionRecordingId),
                buildTimestampCommentContent(currentPlayerTime, sessionRecordingId),
            ])
        })
    }

    return (
        <IconWithCount count={currentNotebooks.length ?? 0} showZero={false}>
            <Popover
                visible={!!showPopover}
                onClickOutside={() => {
                    setShowPopover(!showPopover)
                }}
                actionable
                overlay={
                    <div className="space-y-2 max-w-160 flex flex-col">
                        <LemonInput
                            type="search"
                            placeholder="Search notebooks..."
                            value={searchQuery}
                            onChange={setSearchQuery}
                            fullWidth
                        />
                        <LemonDivider className="my-1" />
                        <div>
                            <h5>Continue in</h5>
                            <NotebooksChoiceList
                                notebooksLoading={notebooksLoading}
                                notebooks={currentNotebooks.filter((notebook) => {
                                    // TODO follow-up on filtering after https://github.com/PostHog/posthog/pull/17027
                                    return (
                                        searchQuery.length === 0 ||
                                        notebook.title?.toLowerCase().includes(searchQuery.toLowerCase())
                                    )
                                })}
                                emptyState={
                                    !!searchQuery.length ? 'No matching notebooks' : "You don't have any notebooks"
                                }
                                loadingState={'Loading...'}
                                onClick={async (notebookShortId) => {
                                    setShowPopover(false)
                                    await commentInExistingNotebook(notebookShortId)
                                }}
                            />
                            <h5>Add to</h5>
                            <NotebooksChoiceList
                                notebooksLoading={notebooksLoading}
                                notebooks={allNotebooks.filter((notebook) => {
                                    // TODO follow-up on filtering after https://github.com/PostHog/posthog/pull/17027
                                    const isInExisting = currentNotebooks.find(
                                        (existingNotebook) => existingNotebook.short_id === notebook.short_id
                                    )
                                    return (
                                        !isInExisting &&
                                        (searchQuery.length === 0 ||
                                            notebook.title?.toLowerCase().includes(searchQuery.toLowerCase()))
                                    )
                                })}
                                emptyState={
                                    !!searchQuery.length ? 'No matching notebooks' : "You don't have any notebooks"
                                }
                                loadingState={'Loading...'}
                                onClick={async (notebookShortId) => {
                                    setShowPopover(false)
                                    await addToAndCommentInExistingNotebook(notebookShortId)
                                }}
                            />
                        </div>
                        <LemonDivider className="my-1" />
                        <LemonButton fullWidth icon={<IconPlus />} onClick={commentInNewNotebook}>
                            Comment in a new notebook
                        </LemonButton>
                    </div>
                }
            >
                <LemonButton
                    icon={notebooksLoading || allNotebooksLoading ? <Spinner /> : <IconComment />}
                    active={showPopover}
                    onClick={() => setShowPopover(!showPopover)}
                    sideIcon={null}
                    size={size}
                    data-attr={'notebooks-replay-comment-button'}
                >
                    Comment
                </LemonButton>
            </Popover>
        </IconWithCount>
    )
}

export function NotebookCommentButton(props: NotebookCommentButtonProps): JSX.Element {
    // if nodeLogic is available then the comment button is on a recording that _is already and currently in a notebook_
    const nodeLogic = useNotebookNode()

    return nodeLogic ? (
        <LemonButton
            icon={<IconComment />}
            size={props.size}
            data-attr={'notebooks-replay-comment-button-in-a-notebook'}
            onClick={() => {
                // TODO should have something like insertReplayCommentByTimestamp(getCurrentPlayerTime() * 1000, sessionRecordingId)
                // so we can add these in time order if someone is seeking
                const currentPlayerTime = props.getCurrentPlayerTime() * 1000
                nodeLogic.actions.insertReplayCommentByTimestamp(currentPlayerTime, props.sessionRecordingId)
            }}
        >
            Comment
        </LemonButton>
    ) : (
        <RecordingCommentChoice {...props} />
    )
}
