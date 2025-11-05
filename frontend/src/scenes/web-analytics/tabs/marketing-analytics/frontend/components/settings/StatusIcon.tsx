import { IconCheck, IconWarning, IconX } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { ExternalDataSchemaStatus } from '~/types'

import { MarketingSourceStatus, SourceStatus } from '../../logic/marketingAnalyticsLogic'

export const StatusIcon = ({ status, message }: { status: SourceStatus; message: string }): JSX.Element => {
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

function getStatusDisplay(status: SourceStatus): {
    tagType?: 'success' | 'danger' | 'primary'
    icon?: JSX.Element
} {
    switch (status) {
        case ExternalDataSchemaStatus.Completed:
            return { tagType: 'success' }
        case ExternalDataSchemaStatus.Failed:
            return { tagType: 'danger' }
        case ExternalDataSchemaStatus.Running:
            return { tagType: 'primary' }
        case ExternalDataSchemaStatus.Paused:
            return { tagType: 'danger' }
        case ExternalDataSchemaStatus.Cancelled:
            return { tagType: 'danger' }
        case MarketingSourceStatus.Warning:
            return { icon: <IconWarning className="text-warning" /> }
        case MarketingSourceStatus.Error:
            return { icon: <IconX className="text-muted" /> }
        case MarketingSourceStatus.Success:
            return { icon: <IconCheck className="text-success" /> }
        default:
            throw new Error(`Unknown status: ${status}`)
    }
}
