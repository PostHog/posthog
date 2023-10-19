import { BuiltLogic, useValues } from 'kea'
import clsx from 'clsx'
import { notebookLogic } from './notebookLogic'
import { notebookNodeLogicType } from '../Nodes/notebookNodeLogicType'
import { NotebookNodeChildRenderer } from '../Nodes/NodeWrapper'

export const NotebookColumnRight = (): JSX.Element | null => {
    const { isShowingLeftColumn, nodeLogicsWithChildren } = useValues(notebookLogic)

    console.log('NotebookColumnRight', { isShowingLeftColumn, nodeLogicsWithChildren })
    const isShowing = nodeLogicsWithChildren.length && !isShowingLeftColumn

    return (
        <div
            className={clsx('NotebookColumn NotebookColumn--right', {
                'NotebookColumn--showing': isShowing,
            })}
        >
            <div className="NotebookColumn__content">
                {isShowing ? (
                    <>
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

    return (
        <>
            {children?.map((child, i) => (
                <NotebookNodeChildRenderer key={i} nodeLogic={nodeLogic} content={child} />
            ))}
        </>
    )
}
