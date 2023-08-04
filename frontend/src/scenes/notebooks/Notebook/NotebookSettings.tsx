import { useActions, useValues } from 'kea'
import { notebookLogic } from './notebookLogic'
import { Settings as FlagSettings } from '../Nodes/NotebookNodeFlag'
import { LemonButton } from '@posthog/lemon-ui'
import { IconUnfoldLess, IconUnfoldMore } from 'lib/lemon-ui/icons'
import { notebookSettingsWidgetLogic } from './notebookSettingsWidgetLogic'
import { notebookNodeLogicType } from '../Nodes/notebookNodeLogicType'

const settingsComponents = {
    'ph-feature-flag': FlagSettings,
}

export const NotebookSettings = (): JSX.Element | null => {
    const { selectedNodeLogic } = useValues(notebookLogic)

    return (
        <div className="NotebookSettings space-y-2">
            <NotebookSettingsWidget id={'notebook'} title="Notebook Settings">
                <div>Notebook settings</div>
            </NotebookSettingsWidget>
            {selectedNodeLogic && <SelectedNodeSettingsWidget logic={selectedNodeLogic} />}
        </div>
    )
}

const SelectedNodeSettingsWidget = ({ logic }: { logic: notebookNodeLogicType }): JSX.Element | null => {
    if (!Object.keys(settingsComponents).includes(logic.props.nodeType)) {
        return null
    }

    const Settings = settingsComponents[logic.props.nodeType]

    return (
        <NotebookSettingsWidget id={logic.props.nodeId} title={logic.values.title}>
            <Settings attributes={logic.props.nodeAttributes} updateAttributes={logic.actions.updateAttributes} />
        </NotebookSettingsWidget>
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
                <LemonButton
                    onClick={() => setIsExpanded(!isExpanded)}
                    size="small"
                    status="primary-alt"
                    className="flex-1"
                >
                    <span className="flex-1 cursor-pointer">{title}</span>
                </LemonButton>
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
