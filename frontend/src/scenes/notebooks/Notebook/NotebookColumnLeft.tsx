import { LemonButton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { BuiltLogic, useActions, useValues } from 'kea'
import { LemonWidget } from 'lib/lemon-ui/LemonWidget'
import { useEffect, useRef, useState } from 'react'

import { notebookNodeLogicType } from '../Nodes/notebookNodeLogicType'
import { NotebookHistory } from './NotebookHistory'
import { notebookLogic } from './notebookLogic'

export const NotebookColumnLeft = (): JSX.Element | null => {
    const { editingNodeLogic, isShowingLeftColumn, showHistory } = useValues(notebookLogic)

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
                    <LemonButton size="small" status="primary" onClick={() => setEditingNodeId(null)}>
                        Done
                    </LemonButton>
                </>
            }
        >
            <div onClick={() => selectNode()}>
                {Settings ? (
                    <Settings
                        key={nodeAttributes.nodeId}
                        attributes={nodeAttributes}
                        updateAttributes={updateAttributes}
                    />
                ) : null}
            </div>
        </LemonWidget>
    )
}
