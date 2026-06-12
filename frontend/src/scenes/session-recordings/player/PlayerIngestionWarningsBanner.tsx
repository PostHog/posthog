import { useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { playerIngestionWarningsLogic } from './playerIngestionWarningsLogic'
import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'

export function PlayerIngestionWarningsBanner(): JSX.Element | null {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { droppedDataPhrases } = useValues(
        playerIngestionWarningsLogic({ sessionRecordingId: logicProps.sessionRecordingId })
    )

    if (!droppedDataPhrases.length) {
        return null
    }

    return (
        <LemonBanner
            type="warning"
            className="mb-2"
            dismissKey={`replay-ingestion-warnings-${logicProps.sessionRecordingId}`}
        >
            This recording is missing data ({droppedDataPhrases.join('; ')}), so playback may be incomplete.{' '}
            <Link to={urls.ingestionWarnings()}>View ingestion warnings</Link>
        </LemonBanner>
    )
}
