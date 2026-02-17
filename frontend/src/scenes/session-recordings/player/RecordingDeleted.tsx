import { IconTrash } from '@posthog/icons'

import { dayjs } from 'lib/dayjs'
import { humanFriendlyDetailedTime } from 'lib/utils'

interface RecordingDeletedProps {
    deletedAt: number | null
}

export function RecordingDeleted({ deletedAt }: RecordingDeletedProps): JSX.Element {
    return (
        <div className="flex flex-col items-center justify-center p-8 text-center text-wrap-balance max-w-lg mx-auto">
            <div className="w-16 h-16 rounded-full bg-border-bold/10 flex items-center justify-center mb-4">
                <IconTrash className="text-muted-3000 w-8 h-8" />
            </div>
            <h2 className="text-xl font-bold mb-2">Recording permanently deleted</h2>
            <p className="text-muted mb-0">This recording has been permanently deleted and cannot be recovered.</p>
            {deletedAt !== null && (
                <p className="text-muted-3000 text-xs mt-2 mb-0">
                    Deleted {humanFriendlyDetailedTime(dayjs.unix(deletedAt))}
                </p>
            )}
        </div>
    )
}
