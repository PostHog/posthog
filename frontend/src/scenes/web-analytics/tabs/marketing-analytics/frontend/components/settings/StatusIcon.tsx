import { IconCheck, IconWarning, IconX } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

export const StatusIcon = ({
    status,
    message,
}: {
    status: 'success' | 'warning' | 'error' | 'Completed' | 'Failed' | 'Running'
    message: string
}): JSX.Element => {
    const { tagType, icon } = getStatusDisplay(status)

    return (
        <Tooltip title={message}>
            <div className="flex justify-center">
                {icon && <span className="text-lg">{icon}</span>}
                {tagType && <LemonTag type={tagType}>{status}</LemonTag>}
            </div>
        </Tooltip>
    )
}

function getStatusDisplay(status: 'success' | 'warning' | 'error' | 'Completed' | 'Failed' | 'Running'): {
    tagType?: 'success' | 'danger' | 'primary'
    icon?: JSX.Element
} {
    switch (status) {
        case 'Completed':
            return { tagType: 'success' }
        case 'Failed':
            return { tagType: 'danger' }
        case 'Running':
            return { tagType: 'primary' }
        case 'success':
            return { icon: <IconCheck className="text-success" /> }
        case 'warning':
            return { icon: <IconWarning className="text-warning" /> }
        case 'error':
            return { icon: <IconX className="text-muted" /> }
        default:
            return {}
    }
}
