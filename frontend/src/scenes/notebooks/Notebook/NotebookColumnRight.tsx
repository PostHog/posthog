import clsx from 'clsx'
import { BuiltLogic, useValues } from 'kea'

import { uuid } from 'lib/utils/dom'

import { NotebookNodeChildRenderer } from '../Nodes/NodeWrapper'
import { notebookNodeLogicType } from '../Nodes/notebookNodeLogicType'
import { isMarkdownNotebookContent } from './markdownNotebookV2'
import { NotebookKernelInfo } from './NotebookKernelInfo'
import { notebookLogic } from './notebookLogic'
import { NotebookSchemaBrowser } from './NotebookSchemaBrowser'

export const NotebookColumnRight = (): JSX.Element | null => {
    const { content, isShowingLeftColumn, nodeLogicsWithChildren, showKernelInfo, showSchemaBrowser } =
        useValues(notebookLogic)
    const isMarkdownNotebook = isMarkdownNotebookContent(content)
    const shouldShowMarkdownKernelInfo = isMarkdownNotebook && showKernelInfo
    const shouldShowSchemaBrowser = isMarkdownNotebook && showSchemaBrowser
    const isShowing =
        (nodeLogicsWithChildren.length > 0 || shouldShowMarkdownKernelInfo || shouldShowSchemaBrowser) &&
        !isShowingLeftColumn

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
                        {shouldShowMarkdownKernelInfo ? <NotebookKernelInfo /> : null}
                        {shouldShowSchemaBrowser ? <NotebookSchemaBrowser /> : null}
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
                <NotebookNodeChildRenderer key={child.attrs.nodeId} content={child} />
            ))}
        </>
    )
}
