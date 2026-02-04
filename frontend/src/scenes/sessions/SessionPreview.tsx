import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonButton, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { IconOpenInNew, IconPlayCircle } from 'lib/lemon-ui/icons'
import { colonDelimitedDuration } from 'lib/utils'
import { urls } from 'scenes/urls'

import { sessionProfileLogic } from './sessionProfileLogic'

export interface SessionPreviewProps {
    sessionId: string
    onClose?: () => void
}

export function SessionPreview({ sessionId, onClose }: SessionPreviewProps): JSX.Element | null {
    const { loadSessionData } = useActions(sessionProfileLogic({ sessionId }))
    const { sessionData, sessionDataLoading, hasRecording } = useValues(sessionProfileLogic({ sessionId }))

    useEffect(() => {
        loadSessionData()
    }, [loadSessionData, sessionId])

    if (sessionDataLoading && !sessionData) {
        return (
            <div className="p-4 flex items-center justify-center">
                <Spinner />
            </div>
        )
    }

    if (!sessionData) {
        return (
            <div className="p-4 max-w-80">
                <h4 className="mb-1">Session not found</h4>
                <p className="text-muted mb-0">This session may have expired or been deleted.</p>
            </div>
        )
    }

    const profileUrl = urls.sessionProfile(sessionId)

    return (
        <div className="flex flex-col overflow-hidden max-h-96 max-w-80 gap-2">
            <div className="flex items-center justify-between min-h-10 px-2 pt-2">
                <Link to={profileUrl} className="font-semibold font-mono text-sm truncate flex-1">
                    {sessionId.substring(0, 8)}…
                </Link>
                <div className="flex items-center gap-1">
                    {hasRecording && (
                        <Tooltip title="Watch recording">
                            <LemonButton
                                size="small"
                                icon={<IconPlayCircle />}
                                to={urls.replaySingle(sessionId)}
                                onClick={() => onClose?.()}
                            />
                        </Tooltip>
                    )}
                    <Tooltip title="Open in new tab">
                        <LemonButton size="small" icon={<IconOpenInNew />} to={profileUrl} targetBlank />
                    </Tooltip>
                </div>
            </div>

            <div className="px-2 pb-2 space-y-1.5 text-sm">
                <PropertyRow label="Duration" value={colonDelimitedDuration(sessionData.session_duration)} />
                <PropertyRow label="Started" value={<TZLabel time={sessionData.start_timestamp} showSeconds />} />
                {sessionData.entry_current_url && (
                    <PropertyRow
                        label="Entry URL"
                        value={
                            <span className="truncate block max-w-48" title={sessionData.entry_current_url}>
                                {sessionData.entry_current_url}
                            </span>
                        }
                    />
                )}
                {sessionData.channel_type && <PropertyRow label="Channel" value={sessionData.channel_type} />}
                <PropertyRow label="Bounced" value={sessionData.is_bounce ? 'Yes' : 'No'} />
                <PropertyRow label="Pageviews" value={sessionData.pageview_count} />
            </div>

            <div className="border-t px-2 py-2">
                <LemonButton type="secondary" size="small" fullWidth center to={profileUrl} onClick={() => onClose?.()}>
                    View session details
                </LemonButton>
            </div>
        </div>
    )
}

function PropertyRow({ label, value }: { label: string; value: React.ReactNode }): JSX.Element {
    return (
        <div className="flex items-center justify-between gap-2">
            <span className="text-muted shrink-0">{label}</span>
            <span className="font-medium truncate">{value}</span>
        </div>
    )
}
