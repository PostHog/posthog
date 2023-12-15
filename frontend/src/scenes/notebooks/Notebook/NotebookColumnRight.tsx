import clsx from 'clsx'
import { BuiltLogic, useValues } from 'kea'
import { uuid } from 'lib/utils'

import { NotebookNodeChildRenderer } from '../Nodes/NodeWrapper'
import { notebookNodeLogicType } from '../Nodes/notebookNodeLogicType'
import { notebookCommentLogic } from './notebookCommentLogic'
import { NotebookComments } from './NotebookComments'
import { notebookLogic } from './notebookLogic'

export const NotebookColumnRight = (): JSX.Element | null => {
    const { shortId, isShowingLeftColumn, nodeLogicsWithChildren } = useValues(notebookLogic)
    const { isShowingComments } = useValues(notebookCommentLogic({ shortId }))
    const isShowing = (nodeLogicsWithChildren.length || isShowingComments) && !isShowingLeftColumn

    return (
        <div
            className={clsx('NotebookColumn NotebookColumn--right', {
                'NotebookColumn--showing': isShowing,
            })}
        >
            <div className="NotebookColumn__padding" />
            <div className="NotebookColumn__content">
                {isShowing ? (
                    <>
                        {isShowingComments && <NotebookComments />}
                        {nodeLogicsWithChildren.map((x, i) => (
                            <Widgets key={i} nodeLogic={x} />
                        ))}
                    </>
                ) : null}
            </div>
        </div>
    )
}

const Widgets = ({ nodeLogic }: { nodeLogic: BuiltLogic<notebookNodeLogicType> }): JSX.Element => {
    const { children } = useValues(nodeLogic)

    // TODO: IMPORTANT: The nodeId is basically now required, so we should be checking that in the logic
    // otherwise we end up in horrible re-rendering loops
    children.forEach((content) => {
        if (!content.attrs.nodeId) {
            content.attrs.nodeId = uuid()
        }
    })

    return (
        <>
            {children?.map((child) => (
                <NotebookNodeChildRenderer key={child.attrs.nodeId} nodeLogic={nodeLogic} content={child} />
            ))}
        </>
    )
}
