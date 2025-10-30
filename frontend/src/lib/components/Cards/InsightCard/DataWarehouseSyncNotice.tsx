import { IconWarning } from '@posthog/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { DataWarehouseSyncStatus } from '~/types'

interface DataWarehouseSyncNoticeProps {
    syncStatus: DataWarehouseSyncStatus[] | null | undefined
}

export function DataWarehouseSyncNotice({ syncStatus }: DataWarehouseSyncNoticeProps): JSX.Element | null {
    if (!syncStatus || syncStatus.length === 0) {
        return null
    }

    const failedSyncs = syncStatus.filter((s) => s.status === 'failed')
    const disabledSyncs = syncStatus.filter((s) => s.status === 'disabled')
    const pausedSyncs = syncStatus.filter((s) => s.status === 'paused')

    // Prioritize showing failed syncs first
    const primaryIssues = failedSyncs.length > 0 ? failedSyncs : disabledSyncs.length > 0 ? disabledSyncs : pausedSyncs

    if (primaryIssues.length === 0) {
        return null
    }

    const type = failedSyncs.length > 0 ? 'error' : 'warning'
    const primaryIssue = primaryIssues[0]

    // Build the message
    let message = primaryIssue.message
    if (primaryIssues.length > 1) {
        message = `${message} (and ${primaryIssues.length - 1} other table${primaryIssues.length > 2 ? 's' : ''})`
    }

    return (
        <LemonBanner type={type} className="mb-2" icon={<IconWarning />}>
            <div>
                <strong>Data may be out of date</strong>
                <div className="text-sm mt-1">{message}</div>
                {primaryIssue.error && (
                    <div className="text-xs mt-1 text-muted">
                        <strong>Error:</strong> {primaryIssue.error}
                    </div>
                )}
            </div>
        </LemonBanner>
    )
}
