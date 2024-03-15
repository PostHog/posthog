import { IconFeatures } from '@posthog/icons'
import { LemonButton, LemonTable, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { urls } from 'scenes/urls'

import { SessionPlayerModal } from '../player/modal/SessionPlayerModal'
import { sessionPlayerModalLogic } from '../player/modal/sessionPlayerModalLogic'
import { sessionRecordingErrorsLogic } from './sessionRecordingErrorsLogic'

export function SessionRecordingErrors(): JSX.Element {
    const { openSessionPlayer } = useActions(sessionPlayerModalLogic)
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
        <>
            <SessionPlayerModal />
            <LemonTable
                columns={[
                    {
                        title: 'Error',
                        dataIndex: 'cluster',
                        render: (_, cluster) => (
                            <LemonTableLink
                                title={
                                    String(cluster.cluster) +
                                    'sdvsdn bsdbvo asdvabfdsgfnbv sdvas vafv adfvdvbd fv vdvbsdf'
                                }
                                to={urls.replaySingle(cluster.samples[0].session_id)}
                                onClick={(e) => {
                                    e.preventDefault()
                                    openSessionPlayer({ id: cluster.samples[0].session_id })
                                }}
                            />
                        ),
                    },
                    {
                        title: 'Occurrences',
                        dataIndex: 'occurrences',
                        sorter: (a, b) => a.occurrences - b.occurrences,
                    },
                    {
                        title: 'Unique sessions',
                        dataIndex: 'unique_sessions',
                        sorter: (a, b) => a.unique_sessions - b.unique_sessions,
                    },
                    {
                        title: 'Viewed',
                        dataIndex: 'viewed',
                        render: function Render(_, cluster) {
                            return `${(cluster.viewed / cluster.unique_sessions) * 100}% (${cluster.viewed} of ${
                                cluster.unique_sessions
                            })`
                        },
                        sorter: (a, b) => a.viewed - b.viewed,
                    },
                    {
                        title: 'Actions',
                        render: function Render(_, cluster) {
                            return (
                                <LemonButton
                                    tooltip={`Create a playlist with ${cluster.samples.length} examples`}
                                    type="secondary"
                                    onClick={() => {}}
                                    className="p-2 whitespace-nowrap"
                                >
                                    Create playlist
                                </LemonButton>
                            )
                        },
                    },
                ]}
                dataSource={errors}
                expandable={{ expandedRowRender: () => <div>Hello</div> }}
            />
        </>
    )
}
