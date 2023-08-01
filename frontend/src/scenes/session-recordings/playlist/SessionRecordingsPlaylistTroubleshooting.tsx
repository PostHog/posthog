import { Link } from '@posthog/lemon-ui'

export const SessionRecordingsPlaylistTroubleshooting = (): JSX.Element => {
    return (
        <>
            <h3 className="title align-center text-muted mb-0">No matching recordings</h3>
            <div className="flex flex-col space-y-2">
                <p className="text-muted description m-0">
                    Recordings may not be found for a variety of reasons including:
                </p>

                <ul className="space-y-1">
                    <li>
                        <Link to="https://posthog.com/docs/session-replay/data-retention" target="_blank">
                            They are outside the retention period
                        </Link>
                    </li>
                    <li>
                        <Link
                            to="https://posthog.com/docs/session-replay/troubleshooting#4-adtracking-blockers"
                            target="_blank"
                        >
                            An ad blocker prevented recording
                        </Link>
                    </li>
                    <li>
                        <Link
                            to="https://posthog.com/docs/session-replay/troubleshooting#1-authorized-domains-for-recordings"
                            target="_blank"
                        >
                            Your domain is not authorized
                        </Link>
                    </li>
                </ul>
            </div>
        </>
    )
}
