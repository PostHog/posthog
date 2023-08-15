import { useValues } from 'kea'
import { notebookLogic } from './notebookLogic'
import { Settings as RecordingSettings } from '../Nodes/NotebookNodeRecording'
import { NotebookNodeType, NotebookNodeWidgetSettings } from '~/types'
import { LemonWidget } from 'lib/lemon-ui/LemonWidget'

export const NotebookSettings = (): JSX.Element | null => {
    const { selectedNodeLogic } = useValues(notebookLogic)

    return selectedNodeLogic && selectedNodeLogic.values.hasSettings ? (
        <div className="NotebookSettings space-y-2">
            <LemonWidget title={selectedNodeLogic.values.title}>
                <SelectedNodeSettingsWidget
                    nodeType={selectedNodeLogic.props.nodeType}
                    attributes={selectedNodeLogic.props.nodeAttributes}
                    updateAttributes={selectedNodeLogic.actions.updateAttributes}
                />
            </LemonWidget>
        </div>
    ) : null
}

const SelectedNodeSettingsWidget = ({
    nodeType,
    ...props
}: {
    nodeType: NotebookNodeType
} & NotebookNodeWidgetSettings): JSX.Element | null => {
    switch (nodeType) {
        case NotebookNodeType.Recording:
            return <RecordingSettings {...props} />
        default:
            return <></>
    }
}
