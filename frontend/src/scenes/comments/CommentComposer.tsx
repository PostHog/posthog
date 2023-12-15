import { LemonButton, LemonTextAreaMarkdown } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { commentsLogic, CommentsLogicProps } from './commentsLogic'

export const CommentComposer = (props: CommentsLogicProps): JSX.Element => {
    const { composedComment, commentsLoading } = useValues(commentsLogic(props))
    const { setComposedComment, sendComposedContent } = useActions(commentsLogic(props))

    const placeholder =
        props.scope !== 'Misc'
            ? `Comment on ${props.scope}/${props.item_id ?? 'general'}`
            : props.item_id
            ? `Comment on ${props.item_id}`
            : `Comment`

    return (
        <div className="space-y-2">
            <LemonTextAreaMarkdown
                data-attr={'comment-composer'}
                placeholder={placeholder}
                value={composedComment}
                onChange={setComposedComment}
                disabled={commentsLoading}
                onPressCmdEnter={sendComposedContent}
            />
            <div className="flex justify-between items-center gap-2">
                <div className="flex-1" />
                <LemonButton
                    type="primary"
                    onClick={sendComposedContent}
                    disabledReason={!composedComment ? 'No message' : null}
                    sideIcon={<KeyboardShortcut command enter />}
                >
                    Add comment
                </LemonButton>
            </div>
        </div>
    )
}
