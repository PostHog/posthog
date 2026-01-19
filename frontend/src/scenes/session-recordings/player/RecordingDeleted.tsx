import { dayjs } from 'lib/dayjs'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { humanFriendlyDetailedTime } from 'lib/utils'

interface RecordingDeletedProps {
    deletedAt: number | null
}

export function RecordingDeleted({ deletedAt }: RecordingDeletedProps): JSX.Element {
    const deletedAtFormatted = deletedAt ? humanFriendlyDetailedTime(dayjs.unix(deletedAt)) : null

    return (
        <div className="flex flex-col items-center justify-center p-8 text-center">
            <h1 className="text-2xl font-bold mb-4">Recording permanently deleted</h1>
            <p className="text-muted mb-6 max-w-md">
                This recording has been permanently deleted and cannot be recovered. The recording data has been
                cryptographically shredded to ensure it cannot be accessed.
            </p>
            {deletedAtFormatted && (
                <LemonBanner type="info" className="max-w-md">
                    <p>Deleted {deletedAtFormatted}</p>
                </LemonBanner>
            )}
        </div>
    )
}
