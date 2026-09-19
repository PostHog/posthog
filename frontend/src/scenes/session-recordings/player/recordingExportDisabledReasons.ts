import { getVideoExportDisabledReason } from 'lib/components/ExportButton/exportStatus'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

export const VIDEO_EXPORT_LIMIT_REACHED = 'You have reached your export limit.'

export interface RecordingExportDisabledReasons {
    json?: string
    video?: string
}

/** Both export actions are offered from the overflow menu and from the expiry warning, so they
 * share one gate to stop the two surfaces from disagreeing about what a person can export. */
export function getRecordingExportDisabledReasons(
    durationMs: number | undefined,
    hasReachedExportFullVideoLimit: boolean
): RecordingExportDisabledReasons {
    // Creating an export requires editor access to the export resource.
    const accessReason =
        getAccessControlDisabledReason(AccessControlResourceType.Export, AccessControlLevel.Editor) ?? undefined

    return {
        json: accessReason,
        video:
            (hasReachedExportFullVideoLimit ? VIDEO_EXPORT_LIMIT_REACHED : undefined) ??
            getVideoExportDisabledReason(durationMs) ??
            accessReason,
    }
}
