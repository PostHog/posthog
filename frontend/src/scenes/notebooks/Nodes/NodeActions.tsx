import { LemonButton } from '@posthog/lemon-ui'
import { IconClose } from 'lib/lemon-ui/icons'

export const NodeActions = ({
    widgets,
    onClickDelete,
    onSelectWidget,
}: {
    widgets: any[]
    onClickDelete: () => void
    onSelectWidget: (key: string) => void
}): JSX.Element => {
    return (
        <div className="NotebookNodeActions space-y-1">
            {widgets.map((widget) => (
                <LemonButton
                    key={widget.key}
                    type="secondary"
                    size="small"
                    tooltip={widget.label}
                    tooltipPlacement="left"
                    icon={widget.icon}
                    onClick={() => onSelectWidget(widget.key)}
                />
            ))}
            <LemonButton
                type="secondary"
                status="danger"
                size="small"
                tooltip="Settings"
                tooltipPlacement="right"
                icon={<IconClose />}
                onClick={onClickDelete}
            />
        </div>
    )
}
