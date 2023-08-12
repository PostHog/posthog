import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { IconComment } from 'lib/lemon-ui/icons'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { notebookCommentButtonLogic } from 'scenes/notebooks/NotebookCommentButton/notebookCommentButtonLogic'
import { useActions, useValues } from 'kea'
import { LemonMenuProps } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { dayjs } from 'lib/dayjs'
import { NotebookNodeType, NotebookTarget } from '~/types'
import { buildTimestampCommentContent } from 'scenes/notebooks/Nodes/NotebookNodeReplayTimestamp'
import { notebooksListLogic, openNotebook } from 'scenes/notebooks/Notebook/notebooksListLogic'

interface NotebookCommentButtonProps extends Pick<LemonButtonProps, 'size'>, Pick<LemonMenuProps, 'visible'> {
    sessionRecordingId: string
    getCurrentPlayerTime: () => number
}

export function NotebookCommentButton({
    sessionRecordingId,
    getCurrentPlayerTime,
    size = 'small',
    // allows a caller to determine whether the pop-over starts open or closed
    visible = undefined,
}: NotebookCommentButtonProps): JSX.Element {
    const logic = notebookCommentButtonLogic({ sessionRecordingId })
    const { notebooksLoading, notebooks } = useValues(logic)
    const { createNotebook } = useActions(notebooksListLogic)

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
                notebookCommentButtonLogic.findMounted({ sessionRecordingId })?.actions.loadNotebooks()
            }
        )
    }

    const commentInExistingNotebook = async (notebookShortId: string): Promise<void> => {
        const currentPlayerTime = getCurrentPlayerTime() * 1000
        await openNotebook(notebookShortId, NotebookTarget.Popover, null, (theNotebookLogic) => {
            const ed = theNotebookLogic.values.editor
            if (ed === null) {
                // this should never happen, `openNotebook` waits until the logic's editor is not null
                return
            }
            const recordingPosition = ed.findNodePositionByAttrs({ id: sessionRecordingId })
            theNotebookLogic.actions.insertAfterLastNodeOfType(
                NotebookNodeType.ReplayTimestamp,
                [buildTimestampCommentContent(currentPlayerTime, sessionRecordingId)],
                recordingPosition
            )
        })
    }

    return (
        <LemonMenu
            visible={visible}
            items={[
                {
                    items: notebooksLoading
                        ? [
                              {
                                  label: () => (
                                      <div className={'px-2 py-1 flex flex-row items-center space-x-1'}>
                                          <Spinner />
                                          <span>Finding notebooks with this recording...</span>
                                      </div>
                                  ),
                                  custom: true,
                              },
                          ]
                        : notebooks.length === 0
                        ? [
                              {
                                  label: () => (
                                      <div className={'px-2 py-1'}>This recording is not already in any notebooks.</div>
                                  ),
                                  custom: true,
                              },
                          ]
                        : notebooks.map((notebook) => ({
                              label: notebook.title || 'unknown title',
                              onClick: () => {
                                  commentInExistingNotebook(notebook.short_id)
                              },
                          })),
                },
                {
                    label: 'Comment in a new notebook',
                    onClick: commentInNewNotebook,
                },
            ]}
        >
            <LemonButton icon={notebooksLoading ? <Spinner /> : <IconComment />} size={size}>
                Comment
            </LemonButton>
        </LemonMenu>
    )
}
