import { LemonWidget } from 'lib/lemon-ui/LemonWidget'
import { BuiltLogic, useActions, useValues } from 'kea'
import clsx from 'clsx'
import { notebookLogic } from './notebookLogic'
import { notebookNodeLogicType } from '../Nodes/notebookNodeLogicType'
import { LemonButton } from '@posthog/lemon-ui'
import { IconEyeVisible } from 'lib/lemon-ui/icons'
import { NotebookHistory } from './NotebookHistory'

export const NotebookColumnLeft = (): JSX.Element | null => {
    const { editingNodeLogic, isShowingLeftColumn, showHistory } = useValues(notebookLogic)

    return (
        <div
            className={clsx('NotebookColumn NotebookColumn--left', {
                'NotebookColumn--showing': isShowingLeftColumn,
            })}
        >
            <div className="NotebookColumn__padding" />
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
                    <LemonButton icon={<IconEyeVisible />} size="small" status="primary" onClick={() => selectNode()} />
                    <LemonButton size="small" status="primary" onClick={() => setEditingNodeId(null)}>
                        Done
                    </LemonButton>
                </>
            }
        >
            {Settings ? (
                <Settings key={nodeAttributes.nodeId} attributes={nodeAttributes} updateAttributes={updateAttributes} />
            ) : null}
        </LemonWidget>
    )
}
