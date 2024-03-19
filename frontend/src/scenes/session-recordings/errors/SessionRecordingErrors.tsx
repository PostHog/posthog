import { IconFeatures } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTabs, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { JSONViewer } from 'lib/components/JSONViewer'
import { useState } from 'react'
import { urls } from 'scenes/urls'

import { SessionPlayerModal } from '../player/modal/SessionPlayerModal'
import { sessionPlayerModalLogic } from '../player/modal/sessionPlayerModalLogic'
import { sessionRecordingErrorsLogic } from './sessionRecordingErrorsLogic'

const MAX_TITLE_LENGTH = 75

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
            <LemonTable
                columns={[
                    {
                        title: 'Error',
                        dataIndex: 'cluster',
                        render: (_, cluster) => {
                            const displayTitle = parseTitle(cluster.sample.error)
                            return (
                                <div title={displayTitle} className="font-semibold text-sm text-default line-clamp-1">
                                    {displayTitle}
                                </div>
                            )
                        },
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
                        tooltip: "How many of these you've already viewed",
                        dataIndex: 'viewed',
                        render: function Render(_, cluster) {
                            return `${((cluster.viewed / cluster.unique_sessions) * 100).toFixed(0)}%`
                        },
                        sorter: (a, b) => a.viewed / a.unique_sessions - b.viewed / b.unique_sessions,
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
            <SessionPlayerModal />
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
        <div className="py-3 space-y-1">
            <h3>Example error</h3>
            <div className="whitespace-pre-line">{error}</div>
        </div>
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

function parseTitle(error: string): string {
    let input
    try {
        const parsedError = JSON.parse(error)
        input = parsedError.error || error
    } catch {
        input = error
    }

    return input.split('\n')[0].trim().substring(0, MAX_TITLE_LENGTH)
}
