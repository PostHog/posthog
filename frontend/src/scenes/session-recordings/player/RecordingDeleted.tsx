import { dayjs } from 'lib/dayjs'
import { humanFriendlyDetailedTime } from 'lib/utils'

interface RecordingDeletedProps {
    deletedAt: number | null
}

export function RecordingDeleted({ deletedAt }: RecordingDeletedProps): JSX.Element {
    const deletedAtFormatted = deletedAt ? humanFriendlyDetailedTime(dayjs.unix(deletedAt)) : null

    return (
        <div className="NotFoundComponent">
            <div className="NotFoundComponent__graphic" />
            <h1 className="text-2xl font-bold mt-4 mb-0">Recording permanently deleted</h1>
            <p className="text-sm font-semibold italic mt-3 mb-0">This data is gone for good.</p>
            <p className="text-sm mt-3 mb-0">
                This recording has been permanently deleted and cannot be recovered.
                {deletedAtFormatted && (
                    <>
                        <br />
                        Deleted {deletedAtFormatted}.
                    </>
                )}
            </p>
        </div>
    )
}
