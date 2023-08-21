import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'

import { IconJournalPlus, IconPlus, IconWithCount } from 'lib/lemon-ui/icons'
import {
    NotebookAddButtonLogicProps,
    notebookAddButtonLogic,
} from 'scenes/notebooks/NotebookAddButton/notebookAddButtonLogic'
import { BindLogic, BuiltLogic, useActions, useValues } from 'kea'
import { LemonMenuProps } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { dayjs } from 'lib/dayjs'
import { NotebookListItemType, NotebookTarget } from '~/types'
import { notebooksModel, openNotebook } from '~/models/notebooksModel'
import { useNotebookNode } from 'scenes/notebooks/Nodes/notebookNodeLogic'
import { Popover } from 'lib/lemon-ui/Popover'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { notebookLogicType } from '../Notebook/notebookLogicType'
import { notebookNodeLogicType } from '../Nodes/notebookNodeLogicType'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'

type NotebookAddButtonProps = NotebookAddButtonLogicProps &
    Omit<LemonButtonProps, 'onClick'> &
    Pick<LemonMenuProps, 'visible'> & {
        newNotebookTitle?: string
        onNotebookOpened?: (
            notebookLogic: BuiltLogic<notebookLogicType>,
            nodeLogic?: BuiltLogic<notebookNodeLogicType>
        ) => void
        onClick?: () => void
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
                            {notebook.title || `Untitled (${notebook.short_id})`}
                        </LemonButton>
                    )
                })
            )}
        </div>
    )
}

function NotebooksChoicePopoverBody(props: NotebookAddButtonProps): JSX.Element {
    const { containingNotebooks, containingNotebooksLoading, allNotebooks, allNotebooksLoading, searchQuery } =
        useValues(notebookAddButtonLogic)
    const { setShowPopover } = useActions(notebookAddButtonLogic)

    const openAndAddToNotebook = async (notebookShortId: string, exists: boolean): Promise<void> => {
        await openNotebook(notebookShortId, NotebookTarget.Popover, null, (theNotebookLogic) => {
            if (!exists) {
                theNotebookLogic.actions.insertAfterLastNode([props.resource])
            }
            props.onNotebookOpened?.(theNotebookLogic)
        })
    }

    if (allNotebooks.length === 0 && containingNotebooks.length === 0) {
        return (
            <div className={'px-2 py-1 flex flex-row items-center space-x-1'}>
                {allNotebooksLoading || containingNotebooksLoading ? (
                    'Loading...'
                ) : searchQuery.length ? (
                    <>No matching notebooks</>
                ) : (
                    <>You have no notebooks</>
                )}
            </div>
        )
    }

    return (
        <>
            {containingNotebooks.length ? (
                <>
                    <h5>Continue in</h5>
                    <NotebooksChoiceList
                        notebooks={containingNotebooks.filter((notebook) => {
                            // notebook comment logic doesn't know anything about backend filtering 🤔
                            return (
                                searchQuery.length === 0 ||
                                notebook.title?.toLowerCase().includes(searchQuery.toLowerCase())
                            )
                        })}
                        emptyState={searchQuery.length ? 'No matching notebooks' : 'Not already in any notebooks'}
                        onClick={async (notebookShortId) => {
                            setShowPopover(false)
                            await openAndAddToNotebook(notebookShortId, true)
                        }}
                    />
                </>
            ) : null}
            {allNotebooks.length > containingNotebooks.length && (
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
                                (searchQuery.length === 0 ||
                                    notebook.title?.toLowerCase().includes(searchQuery.toLowerCase()))
                            )
                        })}
                        emptyState={searchQuery.length ? 'No matching notebooks' : "You don't have any notebooks"}
                        onClick={async (notebookShortId) => {
                            setShowPopover(false)
                            await openAndAddToNotebook(notebookShortId, false)
                        }}
                    />
                </>
            )}
        </>
    )
}

function NotebookAddButtonPopover({ ...props }: NotebookAddButtonProps): JSX.Element {
    const { resource, newNotebookTitle, children } = props
    const logic = notebookAddButtonLogic(props)
    const { showPopover, notebooksLoading, containingNotebooks, searchQuery } = useValues(logic)
    const { setShowPopover, setSearchQuery, loadContainingNotebooks } = useActions(logic)
    const { createNotebook } = useActions(notebooksModel)

    const openNewNotebook = (): void => {
        const title = newNotebookTitle ?? `Notes ${dayjs().format('DD/MM')}`
        // const title = newNotebookTitle ?? `Session Replay Notes ${dayjs().format('DD/MM')}`
        // const currentPlayerTime = getCurrentPlayerTime() * 1000
        createNotebook(title, NotebookTarget.Popover, [resource], (theNotebookLogic) => {
            props.onNotebookOpened?.(theNotebookLogic)
            loadContainingNotebooks()
        })

        setShowPopover(false)
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
                            value={searchQuery}
                            onChange={(s) => setSearchQuery(s)}
                            fullWidth
                        />
                        <LemonDivider className="my-1" />
                        <div>
                            <BindLogic logic={notebookAddButtonLogic} props={props}>
                                <NotebooksChoicePopoverBody {...props} />
                            </BindLogic>
                        </div>
                        <LemonDivider className="my-1" />
                        <LemonButton fullWidth icon={<IconPlus />} onClick={openNewNotebook}>
                            New notebook
                        </LemonButton>
                    </div>
                }
            >
                <LemonButton
                    icon={<IconJournalPlus />}
                    sideIcon={null}
                    {...props}
                    active={showPopover}
                    loading={notebooksLoading}
                    onClick={() => {
                        props.onClick?.()
                        setShowPopover(!showPopover)
                    }}
                    data-attr={'notebooks-add-button'}
                >
                    {children ?? 'Add to notebook'}
                </LemonButton>
            </Popover>
        </IconWithCount>
    )
}

export function NotebookAddButton({ ...props }: NotebookAddButtonProps): JSX.Element {
    // if nodeLogic is available then the button is on a resource that _is already and currently in a notebook_
    const nodeLogic = useNotebookNode()

    return (
        <FlaggedFeature flag={FEATURE_FLAGS.NOTEBOOKS} match>
            {nodeLogic ? (
                <LemonButton
                    icon={<IconJournalPlus />}
                    data-attr={'notebooks-add-button-in-a-notebook'}
                    {...props}
                    onClick={() => {
                        props.onClick?.()
                        props.onNotebookOpened?.(nodeLogic.props.notebookLogic, nodeLogic)
                    }}
                >
                    {props.children ?? 'Add to notebook'}
                </LemonButton>
            ) : (
                <NotebookAddButtonPopover {...props} />
            )}
        </FlaggedFeature>
    )
}
