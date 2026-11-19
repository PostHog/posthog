import { IconWarning } from '@posthog/icons'
import { Text } from '@posthog/quill'

interface DashboardV2PanelMessageProps {
    title: string
    detail?: string
}

export function DashboardV2PanelMessage({ title, detail }: DashboardV2PanelMessageProps): JSX.Element {
    return (
        <div
            className="flex h-full min-h-0 flex-col items-center justify-center gap-1 overflow-hidden text-center"
            data-attr="dashboard-v2-panel-message"
        >
            <Text size="sm" className="flex items-center gap-1">
                <IconWarning className="text-warning-foreground" />
                {title}
            </Text>
            {detail && (
                <Text size="xs" variant="muted" className="line-clamp-3 break-words">
                    {detail}
                </Text>
            )}
        </div>
    )
}
