import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { IconComment } from 'lib/lemon-ui/icons'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { notebookCommentButtonLogic } from 'scenes/notebooks/NotebookCommentButton/notebookCommentButtonLogic'
import { useValues } from 'kea'
import { LemonMenuProps } from 'lib/lemon-ui/LemonMenu/LemonMenu'

interface NotebookCommentButtonProps extends Pick<LemonButtonProps, 'size'>, Pick<LemonMenuProps, 'visible'> {
    sessionRecordingId: string
    onCommentInNewNotebook: () => void
    onCommentInExistingNotebook: (notebookShortId: string) => void
}

/** A wrapper for the button, that lets you open a new or an existing recording
 */
export function NotebookCommentButton({
    sessionRecordingId,
    onCommentInNewNotebook,
    onCommentInExistingNotebook,
    size = 'small',
    // allows a caller to determine whether the pop-over starts open or closed
    visible = undefined,
}: NotebookCommentButtonProps): JSX.Element {
    const logic = notebookCommentButtonLogic({ sessionRecordingId })
    const { notebooksLoading, notebooks } = useValues(logic)
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
                                  onCommentInExistingNotebook(notebook.short_id)
                              },
                          })),
                },
                {
                    label: 'Comment in a new notebook',
                    onClick: () => {
                        onCommentInNewNotebook()
                    },
                },
            ]}
        >
            <LemonButton icon={notebooksLoading ? <Spinner /> : <IconComment />} size={size}>
                Comment
            </LemonButton>
        </LemonMenu>
    )
}
