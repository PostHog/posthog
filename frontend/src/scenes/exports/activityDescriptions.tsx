import {
    ActivityLogItem,
    HumanizedChange,
    defaultDescriber,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

export function exportedAssetActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope !== 'ExportedAsset') {
        console.error('exported asset describer received a non-export activity')
        return { description: null }
    }

    if (logItem.activity === 'exported') {
        const exportFormat = logItem.detail.changes?.[0]?.after
        let formatLabel = 'an export'
        if (typeof exportFormat === 'string') {
            formatLabel = `a ${exportFormat.split('/')[1] || exportFormat}`
        }

        return {
            description: (
                <>
                    <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> exported{' '}
                    {asNotification ? 'your ' : ''}
                    <Link to={urls.exports()}>{logItem.detail.name || 'an export'}</Link> as {formatLabel}
                </>
            ),
        }
    }

    return defaultDescriber(logItem, asNotification)
}
