import { LemonButton, Spinner } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { urls } from 'scenes/urls'

import { sessionRecordingDataLogic } from './sessionRecordingDataLogic'
import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'

export function SimilarRecordings(): JSX.Element | null {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { similarRecordings, similarRecordingsLoading } = useValues(sessionRecordingDataLogic(logicProps))

    if (!similarRecordings && !similarRecordingsLoading) {
        return null
    }

    return (
        <div className="absolute bottom-1 left-1 z-10 bg-bg-light p-1">
            {similarRecordingsLoading ? (
                <Spinner />
            ) : !!similarRecordings && similarRecordings?.length > 0 ? (
                <div>
                    <span>Watch similar recordings</span>
                    {similarRecordings?.map(([id, similarity]) => (
                        <LemonButton key={id} type="secondary" to={urls.replaySingle(id)}>
                            {similarity}
                        </LemonButton>
                    ))}
                </div>
            ) : (
                <span>No similar recordings found</span>
            )}
        </div>
    )
}
