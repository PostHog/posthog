import { IconCheck, IconWarning, IconX } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

export const StatusIcon = ({
    status,
    message,
}: {
    status: 'success' | 'warning' | 'error'
    message: string
}): JSX.Element => (
    <Tooltip title={message}>
        <div className="flex justify-center">
            {status === 'success' && <IconCheck className="text-success-foreground text-lg" />}
            {status === 'warning' && <IconWarning className="text-warning-foreground text-lg" />}
            {status === 'error' && <IconX className="text-tertiary-foreground text-lg" />}
        </div>
    </Tooltip>
)
