import { useEffect, useState } from 'react'

import { IconPlay } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTable } from '@posthog/lemon-ui'

import api from 'lib/api'
import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyDuration } from 'lib/utils'
import { urls } from 'scenes/urls'

interface SessionReplaysWidgetProps {
    tileId: number
    config: Record<string, any>
}

interface SessionRecording {
    id: string
    start_time: string
    end_time: string
    recording_duration: number
    distinct_id: string
    viewed: boolean
    person?: {
        distinct_ids: string[]
        properties: Record<string, any>
    }
    activity_score?: number
}

function SessionReplaysWidget({ config }: SessionReplaysWidgetProps): JSX.Element {
    const [recordings, setRecordings] = useState<SessionRecording[]>([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)

    useEffect(() => {
        setLoading(true)
        const params: Record<string, any> = { limit: 10 }
        if (config.date_from) {
            params.date_from = config.date_from
        }
        if (config.date_to) {
            params.date_to = config.date_to
        }

        api.get('api/projects/@current/session_recordings', params)
            .then((data: any) => {
                setRecordings(data.results || [])
                setLoading(false)
            })
            .catch(() => {
                setError('Failed to load session recordings')
                setLoading(false)
            })
    }, [config.date_from, config.date_to])

    if (loading) {
        return (
            <div className="p-4 space-y-2">
                {Array.from({ length: 5 }).map((_, i) => (
                    <LemonSkeleton key={i} className="h-8 w-full" />
                ))}
            </div>
        )
    }

    if (error) {
        return (
            <div className="p-4 flex flex-col items-center justify-center h-full text-muted">
                <IconPlay className="text-3xl mb-2" />
                <span>{error}</span>
            </div>
        )
    }

    return (
        <div className="h-full flex flex-col overflow-hidden">
            <LemonTable
                dataSource={recordings}
                size="small"
                className="flex-1"
                columns={[
                    {
                        title: 'Recording',
                        key: 'id',
                        render: (_, recording) => (
                            <LemonButton type="tertiary" size="xsmall" to={urls.replaySingle(recording.id)}>
                                <div className="flex items-center gap-1">
                                    <IconPlay className="text-xs" />
                                    <span className="truncate max-w-[150px]">
                                        {recording.person?.properties?.email ||
                                            recording.person?.properties?.name ||
                                            recording.distinct_id}
                                    </span>
                                </div>
                            </LemonButton>
                        ),
                    },
                    {
                        title: 'Duration',
                        key: 'duration',
                        width: 80,
                        render: (_, recording) => (
                            <span className="text-xs">{humanFriendlyDuration(recording.recording_duration)}</span>
                        ),
                    },
                    {
                        title: 'Started',
                        key: 'start_time',
                        width: 120,
                        render: (_, recording) => <TZLabel time={recording.start_time} className="text-xs" />,
                    },
                ]}
                rowKey="id"
                emptyState={
                    <div className="text-center py-8 text-muted">
                        <IconPlay className="text-2xl mb-2" />
                        <div>No session recordings found</div>
                    </div>
                }
            />
        </div>
    )
}

export default SessionReplaysWidget
