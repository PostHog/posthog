import { useValues } from 'kea'
import { notebookLogic } from './notebookLogic'
import { Settings as FlagSettings } from '../Nodes/NotebookNodeFlag'

const SettingsComponents = {
    'ph-feature-flag': FlagSettings,
}

export const NotebookWidget = (): JSX.Element | null => {
    const { selectedNodeLogic } = useValues(notebookLogic)

    if (!selectedNodeLogic) {
        return null
    }

    const Settings = SettingsComponents[selectedNodeLogic?.props.nodeType]
    const props = {
        attributes: selectedNodeLogic.props.nodeAttributes,
        updateAttributes: selectedNodeLogic.actions.updateAttributes,
    }

    return (
        <div className="NotebookWidget border p-2 rounded">
            <div>Widgets</div>
            <Settings {...props} />
        </div>
    )
}
