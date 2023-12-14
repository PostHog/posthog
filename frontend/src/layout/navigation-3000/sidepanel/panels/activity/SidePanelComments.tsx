import { LemonDivider } from '@posthog/lemon-ui'
import { CommentComposer } from 'scenes/comments/CommentComposer'
import { CommentsList } from 'scenes/comments/CommentsList'
import { CommentsLogicProps } from 'scenes/comments/commentsLogic'

export const SidePanelComments = (): JSX.Element => {
    const logicProps: CommentsLogicProps = {
        scope: 'Notebook',
    }

    return (
        <div className="flex flex-col overflow-hidden">
            <div className="overfloy-y-auto">
                <CommentsList {...logicProps} />
            </div>

            <LemonDivider />
            <CommentComposer {...logicProps} />
        </div>
    )
}
