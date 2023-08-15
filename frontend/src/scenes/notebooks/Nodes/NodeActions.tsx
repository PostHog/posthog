import { LemonButton } from '@posthog/lemon-ui'
import { IconClose, IconSettings } from 'lib/lemon-ui/icons'

export const NodeActions = ({
    onClickDelete,
    onClickSettings,
}: {
    onClickDelete: () => void
    onClickSettings: () => void
}): JSX.Element => {
    return (
        <div className="NotebookNodeActions space-y-1">
            <LemonButton
                type="secondary"
                size="small"
                tooltip="Settings"
                tooltipPlacement="right"
                icon={<IconSettings />}
                onClick={onClickSettings}
            />
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
