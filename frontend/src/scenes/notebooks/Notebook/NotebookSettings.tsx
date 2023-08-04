import { useActions, useValues } from 'kea'
import { notebookLogic } from './notebookLogic'
import { Settings as FlagSettings } from '../Nodes/NotebookNodeFlag'
import { LemonButton } from '@posthog/lemon-ui'
import { IconUnfoldLess, IconUnfoldMore } from 'lib/lemon-ui/icons'
import { notebookSettingsWidgetLogic } from './notebookSettingsWidgetLogic'

const settingsComponents = {
    'ph-feature-flag': FlagSettings,
}

export const NotebookSettings = (): JSX.Element | null => {
    const { selectedNodeLogic } = useValues(notebookLogic)

    const Settings = selectedNodeLogic ? settingsComponents[selectedNodeLogic.props.nodeType] : null

    return (
        <div className="NotebookSettings space-y-2">
            <NotebookSettingsWidget id={'notebook'} title="Notebook">
                <div>Notebook settings</div>
            </NotebookSettingsWidget>
            {selectedNodeLogic && (
                <NotebookSettingsWidget id={selectedNodeLogic.props.nodeId} title={selectedNodeLogic.values.title}>
                    <Settings
                        attributes={selectedNodeLogic.props.nodeAttributes}
                        updateAttributes={selectedNodeLogic.actions.updateAttributes}
                    />
                </NotebookSettingsWidget>
            )}
        </div>
    )
}

const NotebookSettingsWidget = ({
    id,
    title,
    children,
}: {
    id: string
    title: string
    children: React.ReactChild
}): JSX.Element => {
    const logic = notebookSettingsWidgetLogic({ id })
    const { isExpanded } = useValues(logic)
    const { setIsExpanded } = useActions(logic)

    return (
        <div className="NotebookSettings__widget border rounded">
            <div className="NotebookSettings__widget__header">
                <span className="flex-1 pl-2">{title}</span>
                <LemonButton
                    onClick={() => setIsExpanded(!isExpanded)}
                    size="small"
                    icon={isExpanded ? <IconUnfoldLess /> : <IconUnfoldMore />}
                />
            </div>
            {isExpanded ? <div className="p-1 border-t border-border">{children}</div> : null}
        </div>
    )
}
