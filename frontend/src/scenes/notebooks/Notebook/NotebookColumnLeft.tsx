import clsx from 'clsx'
import { BindLogic, BuiltLogic, useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { LemonWidget } from 'lib/lemon-ui/LemonWidget'

import { ErrorBoundary } from '~/layout/ErrorBoundary'

import { notebookNodeLogic } from '../Nodes/notebookNodeLogic'
import { notebookNodeLogicType } from '../Nodes/notebookNodeLogicType'
import { NotebookHistory } from './NotebookHistory'
import { NotebookTableOfContents } from './NotebookTableOfContents'
import { notebookLogic } from './notebookLogic'

export const NotebookColumnLeft = (): JSX.Element | null => {
    const { editingNodeLogic, isShowingLeftColumn, showHistory, showTableOfContents } = useValues(notebookLogic)

    return (
        <div
            className={clsx('NotebookColumn NotebookColumn--left', {
                'NotebookColumn--showing': isShowingLeftColumn,
            })}
        >
            {editingNodeLogic ? <NotebookNodeSettingsOffset logic={editingNodeLogic} /> : null}
            <div className="NotebookColumn__content">
                {isShowingLeftColumn ? (
                    editingNodeLogic ? (
                        <NotebookNodeSettingsWidget logic={editingNodeLogic} />
                    ) : showHistory ? (
                        <NotebookHistory />
                    ) : showTableOfContents ? (
                        <NotebookTableOfContents />
                    ) : null
                ) : null}
            </div>
        </div>
    )
}

export const NotebookNodeSettingsOffset = ({ logic }: { logic: BuiltLogic<notebookNodeLogicType> }): JSX.Element => {
    const { ref } = useValues(logic)
    const offsetRef = useRef<HTMLDivElement>(null)
    const [height, setHeight] = useState(0)

    useEffect(() => {
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
    }, [ref, offsetRef.current, height])

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
    const { setEditingNodeId } = useActions(notebookLogic)
    const { Settings, nodeAttributes, title } = useValues(logic)
    const { updateAttributes, selectNode } = useActions(logic)

    return (
        <LemonWidget
            title={`Editing '${title}'`}
            className="NotebookColumn__widget"
            actions={
                <>
                    <LemonButton size="small" onClick={() => setEditingNodeId(null)}>
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
