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
import { useEffect } from 'react'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { buildRecordingContent } from 'scenes/notebooks/Nodes/NotebookNodeRecording'

interface NotebookCommentButtonProps extends Pick<LemonButtonProps, 'size'>, Pick<LemonMenuProps, 'visible'> {
    sessionRecordingId: string
    getCurrentPlayerTime: () => number
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
                        <LemonButton key={i} fullWidth onClick={() => props.onClick(notebook.short_id)}>
                            {notebook.title || 'unknown title'}
                        </LemonButton>
                    )
                })
            )}
        </div>
    )
}

function NotebooksChoicePopoverBody({
    visible,
    sessionRecordingId,
    getCurrentPlayerTime,
}: NotebookCommentButtonProps): JSX.Element {
    const logic = notebookCommentButtonLogic({ sessionRecordingId, startVisible: !!visible })
    const { notebooks: containingNotebooks } = useValues(logic)
    const { setShowPopover } = useActions(logic)

    const {
        filteredNotebooks: allNotebooks,
        filters: { search },
    } = useValues(notebooksListLogic)

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
            notebookCommentButtonLogic.findMounted({ sessionRecordingId })?.actions.loadContainingNotebooks(null)
        })
    }

    if (allNotebooks.length === 0 && containingNotebooks.length === 0) {
        return (
            <div className={'px-2 py-1 flex flex-row items-center space-x-1'}>
                {search.length ? <>No matching notebooks</> : <>You have no notebooks</>}
            </div>
        )
    }

    let continueIn: JSX.Element | null = null
    if (containingNotebooks.length && allNotebooks.length) {
        continueIn = (
            <>
                <h5>Continue in</h5>
                <NotebooksChoiceList
                    notebooks={containingNotebooks.filter((notebook) => {
                        // notebook comment logic doesn't know anything about backend filtering 🤔
                        return search.length === 0 || notebook.title?.toLowerCase().includes(search.toLowerCase())
                    })}
                    emptyState={!!search.length ? 'No matching notebooks' : 'Not already in any notebooks'}
                    onClick={async (notebookShortId) => {
                        setShowPopover(false)
                        await commentInExistingNotebook(notebookShortId)
                    }}
                />
            </>
        )
    }

    let addTo: JSX.Element | null = null
    if (allNotebooks.length > containingNotebooks.length) {
        addTo = (
            <>
                <h5>Add to</h5>
                <NotebooksChoiceList
                    notebooks={allNotebooks.filter((notebook) => {
                        // TODO follow-up on filtering after https://github.com/PostHog/posthog/pull/17027
                        const isInExisting = containingNotebooks.some(
                            (containingNotebook) => containingNotebook.short_id === notebook.short_id
                        )
                        return (
                            !isInExisting &&
                            (search.length === 0 || notebook.title?.toLowerCase().includes(search.toLowerCase()))
                        )
                    })}
                    emptyState={!!search.length ? 'No matching notebooks' : "You don't have any notebooks"}
                    onClick={async (notebookShortId) => {
                        setShowPopover(false)
                        await addToAndCommentInExistingNotebook(notebookShortId)
                    }}
                />
            </>
        )
    }

    return (
        <>
            {continueIn}
            {addTo}
        </>
    )
}

function RecordingCommentChoice(props: NotebookCommentButtonProps): JSX.Element {
    const { visible, sessionRecordingId, getCurrentPlayerTime, size } = props

    const logic = notebookCommentButtonLogic({ sessionRecordingId, startVisible: !!visible })
    const { showPopover, notebooksLoading, notebooks: containingNotebooks } = useValues(logic)
    const { setShowPopover, setSearchQuery } = useActions(logic)

    const { createNotebook, loadNotebooks, setFilters } = useActions(notebooksListLogic)
    const { notebooksLoading: allNotebooksLoading, filters } = useValues(notebooksListLogic)

    useEffect(() => {
        // really this should be connected in a logic,
        // but there was a horrible circular dependency confusing matters
        loadNotebooks()
    }, [])

    const isLoading = notebooksLoading || allNotebooksLoading

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
                notebookCommentButtonLogic.findMounted({ sessionRecordingId })?.actions.loadContainingNotebooks(null)
            }
        )
    }

    return (
        <IconWithCount count={containingNotebooks.length ?? 0} showZero={false}>
            <Popover
                visible={!!showPopover}
                onClickOutside={() => {
                    setShowPopover(false)
                }}
                actionable
                overlay={
                    <div className="space-y-2 max-w-160 flex flex-col">
                        <LemonInput
                            type="search"
                            placeholder="Search notebooks..."
                            value={filters.search}
                            onChange={(s) => {
                                setFilters({ search: s })
                                setSearchQuery(s)
                            }}
                            fullWidth
                        />
                        <LemonDivider className="my-1" />
                        <div>
                            <NotebooksChoicePopoverBody {...props} />
                        </div>
                        <LemonDivider className="my-1" />
                        <LemonButton fullWidth icon={<IconPlus />} onClick={commentInNewNotebook}>
                            Comment in a new notebook
                        </LemonButton>
                    </div>
                }
            >
                <LemonButton
                    icon={isLoading ? <Spinner /> : <IconComment />}
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
