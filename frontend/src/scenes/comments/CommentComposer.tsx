import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

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
            <LemonTextArea
                placeholder={placeholder}
                value={composedComment}
                onChange={setComposedComment}
                disabled={commentsLoading}
            />
            <div className="flex justify-between items-center gap-2">
                <div className="flex-1" />
                <LemonButton
                    type="primary"
                    onClick={sendComposedContent}
                    disabledReason={!composedComment ? 'No message' : null}
                >
                    Add comment
                </LemonButton>
            </div>
        </div>
    )
}
