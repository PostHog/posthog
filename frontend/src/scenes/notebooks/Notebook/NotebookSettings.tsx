import { useValues } from 'kea'
import { notebookLogic } from './notebookLogic'
import { Settings as RecordingSettings } from '../Nodes/NotebookNodeRecording'
import { Link } from '@posthog/lemon-ui'
import { IconRecording, IconSettings } from 'lib/lemon-ui/icons'
import { NotebookNodeType, NotebookNodeWidgetSettings } from '~/types'
import { LemonWidget } from 'lib/lemon-ui/LemonWidget'

export const NotebookSettings = (): JSX.Element | null => {
    const { selectedNodeLogic, shouldCollapseSettings } = useValues(notebookLogic)

    return (
        <div className="NotebookSettings space-y-2">
            <LemonWidget title="Notebook" collapsed={shouldCollapseSettings} icon={<IconSettings />}>
                <div>
                    Learn what is possible from the <Link to="/notebooks/template-introduction">template</Link>.
                </div>
            </LemonWidget>
            {selectedNodeLogic && selectedNodeLogic.values.hasSettings ? (
                <LemonWidget
                    title={selectedNodeLogic.values.title}
                    selected={true}
                    collapsed={shouldCollapseSettings}
                    icon={<IconRecording />}
                >
                    <SelectedNodeSettingsWidget
                        nodeType={selectedNodeLogic.props.nodeType}
                        attributes={selectedNodeLogic.props.nodeAttributes}
                        updateAttributes={selectedNodeLogic.actions.updateAttributes}
                    />
                </LemonWidget>
            ) : null}
        </div>
    )
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
