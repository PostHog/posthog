import { useActions, useValues } from 'kea'
import { notebookLogic } from './notebookLogic'
import { Settings as RecordingSettings } from '../Nodes/NotebookNodeRecording'
import { LemonButton, Link } from '@posthog/lemon-ui'
import { IconUnfoldLess, IconUnfoldMore } from 'lib/lemon-ui/icons'
import { notebookSettingsWidgetLogic } from './notebookSettingsWidgetLogic'
import { NotebookNodeType, NotebookNodeWidgetSettings } from '~/types'
import clsx from 'clsx'

export const NotebookSettings = (): JSX.Element | null => {
    const { selectedNodeLogic } = useValues(notebookLogic)

    return (
        <div className="NotebookSettings space-y-2">
            <NotebookSettingsWidget id="notebook" title="Notebook">
                <div>
                    Learn what is possible in a notebook using the{' '}
                    <Link to="/notebooks/template-introduction">template</Link>.
                </div>
            </NotebookSettingsWidget>
            {selectedNodeLogic && selectedNodeLogic.values.hasSettings ? (
                <NotebookSettingsWidget
                    id={selectedNodeLogic.props.nodeId}
                    title={selectedNodeLogic.values.title}
                    onClick={selectedNodeLogic.actions.scrollToNode}
                    classNames="NotebookSettings__widget--selected"
                >
                    <SelectedNodeSettingsWidget
                        nodeType={selectedNodeLogic.props.nodeType}
                        attributes={selectedNodeLogic.props.nodeAttributes}
                        updateAttributes={selectedNodeLogic.actions.updateAttributes}
                    />
                </NotebookSettingsWidget>
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

const NotebookSettingsWidget = ({
    id,
    title,
    children,
    onClick,
    classNames,
}: {
    id: string
    title: string
    children: React.ReactChild
    onClick?: () => void
    classNames?: string
}): JSX.Element => {
    const logic = notebookSettingsWidgetLogic({ id })
    const { isExpanded } = useValues(logic)
    const { setIsExpanded } = useActions(logic)

    return (
        <div className={clsx('NotebookSettings__widget border rounded', classNames)} onClick={onClick}>
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
            {isExpanded ? <div className="px-3 py-2 border-t border-border">{children}</div> : null}
        </div>
    )
}
