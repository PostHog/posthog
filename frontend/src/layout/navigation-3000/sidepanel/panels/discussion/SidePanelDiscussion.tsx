import { useValues } from 'kea'
import { router } from 'kea-router'
import { CommentComposer } from 'scenes/comments/CommentComposer'
import { CommentsList } from 'scenes/comments/CommentsList'
import { CommentsLogicProps } from 'scenes/comments/commentsLogic'

import { SidePanelPaneHeader } from '../../components/SidePanelPaneHeader'

const urlToComments = (path: string): CommentsLogicProps => {
    return {
        scope: 'Misc',
        item_id: path,
    }
}

export const SidePanelDiscussion = (): JSX.Element => {
    const { location } = useValues(router)
    const logicProps = urlToComments(location.pathname)

    return (
        <div className="flex flex-col overflow-hidden flex-1">
            <SidePanelPaneHeader title="Discussion" />

            <div className="flex flex-col flex-1">
                <div className="flex-1 overflow-y-auto p-2">
                    <CommentsList {...logicProps} />
                </div>

                <div className="border-t p-2">
                    <CommentComposer {...logicProps} />
                </div>
            </div>
        </div>
    )
}
