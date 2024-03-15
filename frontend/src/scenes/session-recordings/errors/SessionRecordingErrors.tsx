import { IconFeatures } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTabs, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { JSONViewer } from 'lib/components/JSONViewer'
import { useState } from 'react'
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
                            <div
                                title={cluster.sample.error}
                                className="font-semibold text-sm text-default line-clamp-1"
                            >
                                {cluster.sample.error}
                            </div>
                        ),
                        width: '50%',
                    },
                    {
                        title: 'Occurrences',
                        dataIndex: 'occurrences',
                        sorter: (a, b) => a.occurrences - b.occurrences,
                    },
                    {
                        title: 'Sessions',
                        dataIndex: 'unique_sessions',
                        sorter: (a, b) => a.unique_sessions - b.unique_sessions,
                    },
                    {
                        title: 'Viewed',
                        tooltip: "Percentage of the issue you've already seen in other watched recordings",
                        dataIndex: 'viewed',
                        render: function Render(_, cluster) {
                            return `${(cluster.viewed / cluster.unique_sessions) * 100}%`
                        },
                        sorter: (a, b) => a.viewed - b.viewed,
                    },
                    {
                        title: 'Actions',
                        render: function Render(_, cluster) {
                            return (
                                <LemonButton
                                    to={urls.replaySingle(cluster.sample.session_id)}
                                    onClick={(e) => {
                                        e.preventDefault()
                                        openSessionPlayer({ id: cluster.sample.session_id })
                                    }}
                                    className="p-2 whitespace-nowrap"
                                    type="primary"
                                >
                                    Watch example
                                </LemonButton>
                            )
                        },
                    },
                ]}
                dataSource={errors}
                expandable={{ expandedRowRender: (cluster) => <ExpandedError error={cluster.sample.error} /> }}
            />
        </>
    )
}

const ExpandedError = ({ error }: { error: string }): JSX.Element => {
    const hasJson = isJSON(error)
    const [activeTab, setActiveTab] = useState(hasJson ? 'json' : 'raw')

    return hasJson ? (
        <div className="pb-3">
            <LemonTabs
                activeKey={activeTab}
                onChange={setActiveTab}
                tabs={[
                    hasJson && {
                        key: 'json',
                        label: 'JSON',
                        content: <JSONViewer src={JSON.parse(error)} style={{ whiteSpace: 'pre-wrap' }} />,
                    },
                    { key: 'raw', label: 'Raw', content: <span className="whitespace-pre-line">{error}</span> },
                ]}
            />
        </div>
    ) : (
        <div className="py-3 whitespace-pre-line">{error}</div>
    )
}

function isJSON(str: string): boolean {
    try {
        JSON.parse(str)
        return true
    } catch {
        return false
    }
}
