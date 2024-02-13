import { LemonButton, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'
import { urls } from 'scenes/urls'

import { sessionRecordingDataLogic } from './sessionRecordingDataLogic'
import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'

export function SimilarRecordings(): JSX.Element | null {
    const { endReached, logicProps } = useValues(sessionRecordingPlayerLogic)
    const logic = sessionRecordingDataLogic(logicProps)
    const { similarRecordings, similarRecordingsLoading } = useValues(logic)
    const { fetchSimilarRecordings } = useActions(logic)

    useEffect(() => {
        if (endReached) {
            fetchSimilarRecordings()
        }
    }, [endReached])

    if (!endReached) {
        return null
    }

    return (
        <div className="absolute bottom-1 left-1 z-10 bg-bg-light p-1">
            {similarRecordingsLoading ? (
                <Spinner />
            ) : similarRecordings && similarRecordings?.length > 0 ? (
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
