import { IconFeatures } from '@posthog/icons'
import { LemonButton, LemonCollapse, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { urls } from 'scenes/urls'

import { ErrorClusterSample } from '~/types'

import { sessionRecordingErrorsLogic } from './sessionRecordingErrorsLogic'

export function SessionRecordingErrors(): JSX.Element {
    const { errors, errorsLoading } = useValues(sessionRecordingErrorsLogic)
    const { loadErrorClusters } = useActions(sessionRecordingErrorsLogic)

    if (errorsLoading) {
        return <Spinner />
    }

    if (!errors) {
        return (
            <LemonButton size="large" type="primary" icon={<IconFeatures />} onClick={() => loadErrorClusters()}>
                Automagically find errors
            </LemonButton>
        )
    }

    return (
        <LemonCollapse
            panels={errors.map((error) => ({
                key: error.cluster,
                header: (
                    <ErrorPanelHeader
                        occurrenceCount={error.occurrences}
                        sessionCount={error.unique_sessions}
                        example={error.samples[0]}
                    />
                ),
                content: <ErrorPanelContent samples={error.samples} />,
            }))}
        />
    )
}

const ErrorPanelHeader = ({
    occurrenceCount,
    sessionCount,
    example,
}: {
    occurrenceCount: number
    sessionCount: number
    example: ErrorClusterSample
}): JSX.Element => {
    return (
        <div className="w-full flex justify-between items-center gap-2">
            <span className="truncate">{example.input}</span>
            <div className="flex items-center gap-2">
                <span className="text-muted">
                    {occurrenceCount} occurrences / {sessionCount} sessions
                </span>
                <LemonButton type="secondary" to={urls.replaySingle(example.session_id)}>
                    Watch recording
                </LemonButton>
            </div>
        </div>
    )
}

const ErrorPanelContent = ({ samples }: { samples: ErrorClusterSample[] }): JSX.Element => {
    return (
        <div className="flex flex-col space-y-2">
            {samples.map((error) => (
                <div key={error.session_id} className="flex justify-between items-center">
                    <span>{error.input}</span>
                    <LemonButton type="secondary" to={urls.replaySingle(error.session_id)}>
                        Watch recording
                    </LemonButton>
                </div>
            ))}
        </div>
    )
}
