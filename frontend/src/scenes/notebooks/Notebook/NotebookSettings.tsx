import { LemonWidget } from 'lib/lemon-ui/LemonWidget'
import { NotebookNodeWidget } from './utils'

export const NotebookSettings = ({
    widgets,
    attributes,
    updateAttributes,
    onDismiss,
}: {
    widgets: NotebookNodeWidget[]
    attributes: any
    updateAttributes: (attributes: Record<string, any>) => void
    onDismiss: (key: string) => void
}): JSX.Element | null => {
    return (
        <div className="NotebookSettings space-y-2">
            {widgets.map(({ key, label, Component }) => (
                <LemonWidget key={key} title={label} onClose={() => onDismiss(key)}>
                    <Component attributes={attributes} updateAttributes={updateAttributes} />
                </LemonWidget>
            ))}
        </div>
    )
}
