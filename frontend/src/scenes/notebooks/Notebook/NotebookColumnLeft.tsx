import clsx from 'clsx'
import { BindLogic, BuiltLogic, useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { LemonWidget } from 'lib/lemon-ui/LemonWidget'

import { ErrorBoundary } from '~/layout/ErrorBoundary'

import { notebookNodeLogic } from '../Nodes/notebookNodeLogic'
import { notebookNodeLogicType } from '../Nodes/notebookNodeLogicType'
import { NotebookHistory } from './NotebookHistory'
import { NotebookKernelInfo } from './NotebookKernelInfo'
import { NotebookTableOfContents } from './NotebookTableOfContents'
import { notebookLogic } from './notebookLogic'

export const NotebookColumnLeft = (): JSX.Element | null => {
    const { editingNodeLogicsForLeft, isShowingLeftColumn, showHistory, showKernelInfo, showTableOfContents } =
        useValues(notebookLogic)

    return (
        <div
            className={clsx('NotebookColumn NotebookColumn--left', {
                'NotebookColumn--showing': isShowingLeftColumn,
            })}
        >
            <div className="NotebookColumn__content">
                {isShowingLeftColumn ? (
                    <>
                        {editingNodeLogicsForLeft.map((logic) => (
                            <div key={logic.values.nodeId}>
                                <NotebookNodeSettingsOffset logic={logic} />
                                <NotebookNodeSettingsWidget logic={logic} />
                            </div>
                        ))}
                        {showHistory ? <NotebookHistory /> : null}
                        {showTableOfContents ? <NotebookTableOfContents /> : null}
                        {showKernelInfo ? <NotebookKernelInfo /> : null}
                    </>
                ) : null}
            </div>
        </div>
    )
}

export const NotebookNodeSettingsOffset = ({ logic }: { logic: BuiltLogic<notebookNodeLogicType> }): JSX.Element => {
    const { ref } = useValues(logic)
    const offsetRef = useRef<HTMLDivElement>(null)
    const [height, setHeight] = useState(0)
    const { isVisible: isPageVisible } = usePageVisibility()

    useEffect(() => {
        if (!isPageVisible) {
            return
        }

        // Interval to check the relative positions of the node and the offset div
        // updating the height so that it always is inline
        const updateHeight = (): void => {
            if (ref && offsetRef.current) {
                const newHeight = ref.getBoundingClientRect().top - offsetRef.current.getBoundingClientRect().top

                if (height !== newHeight) {
                    setHeight(newHeight)
                }
            }
        }

        const interval = setInterval(updateHeight, 100)
        updateHeight()

        return () => clearInterval(interval)
    }, [ref, offsetRef.current, height, isPageVisible])

    return (
        <div
            ref={offsetRef}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                height,
            }}
        />
    )
}

export const NotebookNodeSettingsWidget = ({ logic }: { logic: BuiltLogic<notebookNodeLogicType> }): JSX.Element => {
    const { setEditingNodeEditing } = useActions(notebookLogic)
    const { Settings, nodeAttributes, title } = useValues(logic)
    const { updateAttributes, selectNode } = useActions(logic)

    return (
        <LemonWidget
            title={`Editing '${title}'`}
            className="NotebookColumn__widget"
            actions={
                <>
                    <LemonButton size="small" onClick={() => setEditingNodeEditing(nodeAttributes.nodeId, false)}>
                        Done
                    </LemonButton>
                </>
            }
        >
            <div onClick={() => selectNode()}>
                {Settings ? (
                    <ErrorBoundary>
                        <BindLogic logic={notebookNodeLogic} props={{ attributes: nodeAttributes }}>
                            <Settings
                                key={nodeAttributes.nodeId}
                                attributes={nodeAttributes}
                                updateAttributes={updateAttributes}
                            />
                        </BindLogic>
                    </ErrorBoundary>
                ) : null}
            </div>
        </LemonWidget>
    )
}
