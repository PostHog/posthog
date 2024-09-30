import { IconFeatures } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTabs } from '@posthog/lemon-ui'
import { captureException } from '@sentry/react'
import { useActions, useValues } from 'kea'
import { JSONViewer } from 'lib/components/JSONViewer'
import { Sparkline } from 'lib/components/Sparkline'
import { useState } from 'react'
import { urls } from 'scenes/urls'

import { sessionPlayerModalLogic } from '../player/modal/sessionPlayerModalLogic'
import { sessionRecordingErrorsLogic } from './sessionRecordingErrorsLogic'

const MAX_TITLE_LENGTH = 75

export function SessionRecordingErrors(): JSX.Element {
    const { openSessionPlayer } = useActions(sessionPlayerModalLogic)
    const { errors, errorsLoading } = useValues(sessionRecordingErrorsLogic)
    const { loadErrorClusters, createPlaylist } = useActions(sessionRecordingErrorsLogic)

    if (!errors && !errorsLoading) {
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
                            const displayTitle = parseTitle(cluster.sample)
                            return (
                                <div title={displayTitle} className="font-semibold text-sm text-text-3000 line-clamp-1">
                                    {displayTitle}
                                </div>
                            )
                        },
                        width: '50%',
                    },
                    {
                        title: '',
                        render: (_, cluster) => {
                            return (
                                <Sparkline
                                    className="h-8"
                                    labels={Object.keys(cluster.sparkline)}
                                    data={Object.values(cluster.sparkline)}
                                />
                            )
                        },
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
                                <div className="p-2 flex space-x-2">
                                    <LemonButton
                                        to={urls.replaySingle(cluster.session_ids[0])}
                                        onClick={(e) => {
                                            e.preventDefault()
                                            openSessionPlayer({ id: cluster.session_ids[0] })
                                        }}
                                        className="whitespace-nowrap"
                                        type="primary"
                                    >
                                        Watch example
                                    </LemonButton>
                                    <LemonButton
                                        onClick={() => {
                                            createPlaylist(
                                                `Examples of '${parseTitle(cluster.sample)}'`,
                                                cluster.session_ids
                                            )
                                        }}
                                        className="whitespace-nowrap"
                                        type="secondary"
                                        tooltip="Create a playlist of recordings containing this issue"
                                    >
                                        Create playlist
                                    </LemonButton>
                                </div>
                            )
                        },
                    },
                ]}
                loading={errorsLoading}
                dataSource={errors || []}
                expandable={{
                    expandedRowRender: (cluster) => <ExpandedError error={cluster.sample} />,
                }}
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

    if (!input) {
        return error
    }

    try {
        // TRICKY - after json parsing we might not have a string,
        // since the JSON parser will helpfully convert to other types too e.g. have seen objects here
        if (typeof input !== 'string') {
            input = JSON.stringify(input)
        }

        return input.split('\n')[0].trim().substring(0, MAX_TITLE_LENGTH) || error
    } catch (e) {
        captureException(e, { extra: { error }, tags: { feature: 'replay/error-clustering' } })
        return error
    }
}
