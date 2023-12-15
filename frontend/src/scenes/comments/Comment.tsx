import { TZLabel } from '@posthog/apps-common'
import { IconCheck, IconEllipsis, IconPencil } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonTextAreaMarkdown, ProfilePicture } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { CommentType } from '~/types'

import { commentsLogic } from './commentsLogic'

export type CommentProps = {
    comment: CommentType
}

export const Comment = ({ comment }: CommentProps): JSX.Element => {
    const { editingComment, commentsLoading } = useValues(commentsLogic)
    const { deleteComment, setEditingComment, persistEditedComment } = useActions(commentsLogic)

    // TODO: Permissions

    return (
        <div
            className={clsx('border rounded bg-bg-light ', editingComment?.id === comment.id && 'border-primary-3000')}
        >
            <div className="flex-1 flex justify-start p-2 gap-2">
                <ProfilePicture size="xl" name={comment.created_by?.first_name} email={comment.created_by?.email} />

                <div className="flex flex-col flex-1">
                    <div className="flex items-center gap-2">
                        <span className="flex-1 font-semibold ">
                            {comment.created_by?.first_name ?? 'Unknown user'}
                        </span>
                        {comment.created_at ? (
                            <span className="text-xs">
                                <TZLabel time={comment.created_at} />
                            </span>
                        ) : null}

                        <LemonMenu
                            items={[
                                {
                                    icon: <IconPencil />,
                                    label: 'Edit comment',
                                    onClick: () => setEditingComment(comment),
                                },
                                {
                                    icon: <IconCheck />,
                                    label: 'Delete comment',
                                    onClick: () => deleteComment(comment),
                                    // disabledReason: "Only admins can archive other peoples comments"
                                },
                            ]}
                        >
                            <LemonButton icon={<IconEllipsis />} status="stealth" size="small" />
                        </LemonMenu>
                    </div>
                    <LemonMarkdown lowKeyHeadings>{comment.content}</LemonMarkdown>
                    {comment.version ? <span className="text-xs text-muted italic">(edited)</span> : null}
                </div>
            </div>

            {editingComment?.id === comment.id ? (
                <div className="space-y-2 border-t p-2">
                    <LemonTextAreaMarkdown
                        data-attr={'comment-composer'}
                        placeholder={'Edit comment'}
                        value={editingComment.content}
                        onChange={(value) => setEditingComment({ ...editingComment, content: value })}
                        disabled={commentsLoading}
                        onPressCmdEnter={persistEditedComment}
                    />
                    <div className="flex justify-between items-center gap-2">
                        <div className="flex-1" />
                        <LemonButton
                            type="secondary"
                            onClick={() => setEditingComment(null)}
                            disabled={commentsLoading}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={persistEditedComment}
                            disabledReason={
                                !editingComment.content ? 'No message' : commentsLoading ? 'Saving...' : null
                            }
                            sideIcon={<KeyboardShortcut command enter />}
                        >
                            Save changes
                        </LemonButton>
                    </div>
                </div>
            ) : null}
        </div>
    )
}
